from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Awaitable, Callable, Mapping
from urllib.parse import urlsplit

import httpx

from app.domain.provider import FetchRequest, FetchResult, RawPayload, RequestMetadata, RetryMetadata
from app.providers.base import PayloadTooLargeError, PermanentProviderError, TransientProviderError


DEFAULT_SAFE_REQUEST_PARAMETERS = frozenset({"start_date", "end_date", "format", "series", "key"})
DEFAULT_SAFE_RESPONSE_HEADERS = frozenset(
    {
        "content-type",
        "content-length",
        "content-encoding",
        "etag",
        "last-modified",
        "retry-after",
    }
)


@dataclass(frozen=True)
class HttpPolicy:
    connect_timeout: float = 5.0
    read_timeout: float = 30.0
    write_timeout: float = 10.0
    pool_timeout: float = 5.0
    max_connections: int = 10
    max_keepalive_connections: int = 5
    max_response_bytes: int = 10 * 1024 * 1024
    max_attempts: int = 3
    max_elapsed_seconds: float = 60.0
    base_backoff_seconds: float = 0.5
    max_backoff_seconds: float = 10.0
    retry_statuses: frozenset[int] = frozenset({408, 429, 500, 502, 503, 504})

    def __post_init__(self) -> None:
        if self.max_attempts < 1 or self.max_response_bytes < 1:
            raise ValueError("max_attempts and max_response_bytes must be positive")


def create_async_client(
    base_url: str,
    policy: HttpPolicy,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    headers: Mapping[str, str] | None = None,
    allow_insecure_for_tests: bool = False,
) -> httpx.AsyncClient:
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" and not allow_insecure_for_tests:
        raise ValueError("provider base URL must use HTTPS")
    if not parsed.hostname:
        raise ValueError("provider base URL must include a host")
    return httpx.AsyncClient(
        base_url=base_url,
        timeout=httpx.Timeout(
            connect=policy.connect_timeout,
            read=policy.read_timeout,
            write=policy.write_timeout,
            pool=policy.pool_timeout,
        ),
        limits=httpx.Limits(
            max_connections=policy.max_connections,
            max_keepalive_connections=policy.max_keepalive_connections,
        ),
        verify=True,
        follow_redirects=False,
        transport=transport,
        headers=headers,
    )


class RetryingHttpFetcher:
    def __init__(
        self,
        client: httpx.AsyncClient,
        policy: HttpPolicy,
        *,
        safe_request_parameters: frozenset[str] = DEFAULT_SAFE_REQUEST_PARAMETERS,
        safe_response_headers: frozenset[str] = DEFAULT_SAFE_RESPONSE_HEADERS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        self._client = client
        self._policy = policy
        self._safe_request_parameters = safe_request_parameters
        self._safe_response_headers = safe_response_headers
        self._sleep = sleep
        self._random_value = random_value

    async def fetch(self, request: FetchRequest) -> FetchResult:
        started = asyncio.get_running_loop().time()
        delays: list[float] = []
        for attempt in range(1, self._policy.max_attempts + 1):
            try:
                payload = await self._attempt(request)
                return FetchResult(payload=payload, retry=RetryMetadata(attempt, tuple(delays)))
            except TransientProviderError as error:
                elapsed = asyncio.get_running_loop().time() - started
                if attempt >= self._policy.max_attempts:
                    raise TransientProviderError(
                        "provider request exhausted retries", context=error.context
                    ) from error
                retry_after = error.context.get("retry_after")
                delay = self._retry_delay(attempt, retry_after)
                if elapsed + delay > self._policy.max_elapsed_seconds:
                    raise TransientProviderError(
                        "provider request exceeded retry time budget", context=error.context
                    ) from error
                delays.append(delay)
                await self._sleep(delay)
        raise AssertionError("retry loop did not return or raise")

    async def _attempt(self, request: FetchRequest) -> RawPayload:
        context = {"endpoint_name": request.endpoint_name, "dataset": request.dataset}
        target = urlsplit(request.path)
        if target.scheme or target.netloc or not request.path.startswith("/"):
            raise PermanentProviderError("provider request target rejected", context=context)
        try:
            async with self._client.stream("GET", request.path, params=request.parameters) as response:
                if response.is_redirect:
                    raise PermanentProviderError("provider redirect rejected", context=context)
                if response.status_code in self._policy.retry_statuses:
                    retry_after = response.headers.get("retry-after")
                    if retry_after is not None:
                        safe_retry_after = self._safe_retry_after(retry_after)
                        if safe_retry_after is not None:
                            context = {**context, "retry_after": safe_retry_after}
                    raise TransientProviderError("transient provider response", context=context)
                if 400 <= response.status_code:
                    raise PermanentProviderError("permanent provider response", context=context)
                declared_size = response.headers.get("content-length")
                if declared_size:
                    try:
                        if int(declared_size) > self._policy.max_response_bytes:
                            raise PayloadTooLargeError("provider response exceeds size limit", context=context)
                    except ValueError as error:
                        raise PermanentProviderError(
                            "provider returned invalid content length", context=context
                        ) from error
                body = bytearray()
                if response.is_stream_consumed:
                    # Some test/custom transports supply already-buffered bytes.
                    body.extend(response.content)
                else:
                    # ``aiter_bytes`` transparently decompresses encoded responses;
                    # raw storage must consume the provider's wire representation.
                    async for chunk in response.aiter_raw():
                        body.extend(chunk)
                        if len(body) > self._policy.max_response_bytes:
                            raise PayloadTooLargeError(
                                "provider response exceeds size limit", context=context
                            )
                if len(body) > self._policy.max_response_bytes:
                    raise PayloadTooLargeError("provider response exceeds size limit", context=context)
                return RawPayload(
                    body=bytes(body),
                    media_type=response.headers.get("content-type", "application/octet-stream").split(";", 1)[0],
                    response_status=response.status_code,
                    retrieved_at=datetime.now(timezone.utc),
                    request=RequestMetadata(
                        method="GET",
                        endpoint_name=request.endpoint_name,
                        sanitized_parameters=self._sanitize_parameters(request.parameters),
                    ),
                    response_metadata=self._sanitize_headers(response.headers),
                )
        except (httpx.TimeoutException, httpx.NetworkError):
            # Do not retain the httpx exception as a cause: its request URL may
            # contain provider credentials or other non-allowlisted parameters.
            raise TransientProviderError("provider transport failure", context=context) from None

    def _retry_delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(max(float(retry_after), 0.0), self._policy.max_backoff_seconds)
            except ValueError:
                try:
                    parsed = parsedate_to_datetime(retry_after)
                    seconds = (parsed - datetime.now(parsed.tzinfo or timezone.utc)).total_seconds()
                    return min(max(seconds, 0.0), self._policy.max_backoff_seconds)
                except (TypeError, ValueError, OverflowError):
                    pass
        ceiling = min(
            self._policy.base_backoff_seconds * (2 ** (attempt - 1)),
            self._policy.max_backoff_seconds,
        )
        return ceiling * self._random_value()

    @staticmethod
    def _safe_retry_after(value: str) -> str | None:
        try:
            return str(max(float(value), 0.0))
        except ValueError:
            try:
                parsedate_to_datetime(value)
            except (TypeError, ValueError, OverflowError):
                return None
            return value

    def _sanitize_parameters(
        self, parameters: Mapping[str, str | list[str]]
    ) -> dict[str, str | list[str]]:
        return {
            key: value
            for key, value in parameters.items()
            if key.lower() in self._safe_request_parameters
        }

    def _sanitize_headers(self, headers: httpx.Headers) -> dict[str, str]:
        return {
            key.lower(): value
            for key, value in headers.items()
            if key.lower() in self._safe_response_headers
        }
