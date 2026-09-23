from __future__ import annotations

import gzip

import asyncio
from datetime import date

import httpx
import pytest

from app.domain.provider import DateRange, FetchRequest
from app.providers.base import PayloadTooLargeError, PermanentProviderError, TransientProviderError
from app.providers.http import HttpPolicy, RetryingHttpFetcher, create_async_client


def _request(parameters: dict[str, str] | None = None) -> FetchRequest:
    return FetchRequest(
        dataset="test_dataset",
        instruments=("SERIES_A",),
        date_range=DateRange(date(2026, 1, 1), date(2026, 1, 2)),
        endpoint_name="observations",
        path="/observations",
        parameters=parameters or {},
    )


def _run_fetch(
    handler: httpx.MockTransport,
    *,
    policy: HttpPolicy | None = None,
    delays: list[float] | None = None,
) -> object:
    recorded_delays = delays if delays is not None else []

    async def sleep(delay: float) -> None:
        recorded_delays.append(delay)

    async def run() -> object:
        selected_policy = policy or HttpPolicy()
        async with create_async_client(
            "http://provider.test",
            selected_policy,
            transport=handler,
            allow_insecure_for_tests=True,
        ) as client:
            return await RetryingHttpFetcher(
                client, selected_policy, sleep=sleep, random_value=lambda: 1.0
            ).fetch(_request({"start_date": "2026-01-01", "token": "secret"}))

    return asyncio.run(run())


def test_date_range_rejects_reversed_dates() -> None:
    with pytest.raises(ValueError, match="start"):
        DateRange(date(2026, 1, 2), date(2026, 1, 1))


def test_client_requires_https_outside_tests() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        create_async_client("http://provider.test", HttpPolicy())


def test_success_preserves_body_and_allowlisted_metadata() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            content=b'{"value": "1.25"}',
            headers={"Content-Type": "application/json; charset=utf-8", "ETag": "v1", "Set-Cookie": "private"},
        )
    )
    result = _run_fetch(transport)

    assert result.payload.body == b'{"value": "1.25"}'
    assert result.payload.media_type == "application/json"
    assert result.payload.request.sanitized_parameters == {"start_date": "2026-01-01"}
    assert result.payload.response_metadata == {"content-type": "application/json; charset=utf-8", "etag": "v1", "content-length": "17"}
    assert result.retry.attempts == 1


def test_success_preserves_encoded_wire_bytes() -> None:
    class EncodedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield compressed

    compressed = gzip.compress(b'{"value": "1.25"}')
    result = _run_fetch(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                stream=EncodedStream(),
                headers={"Content-Encoding": "gzip"},
            )
        )
    )
    assert result.payload.body == compressed
    assert result.payload.response_metadata["content-encoding"] == "gzip"


def test_empty_success_is_successful_fetch() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b""))
    result = _run_fetch(transport)
    assert result.payload.body == b""


def test_timeout_is_retried_then_succeeds() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("unsafe details", request=request)
        return httpx.Response(200, content=b"ok")

    delays: list[float] = []
    result = _run_fetch(httpx.MockTransport(handler), delays=delays)
    assert result.retry.attempts == 2
    assert delays == [0.5]


def test_rate_limit_honors_retry_after() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200)

    delays: list[float] = []
    result = _run_fetch(httpx.MockTransport(handler), delays=delays)
    assert result.retry.attempts == 2
    assert delays == [2.0]


def test_retry_exhaustion_contains_only_safe_context() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"password=do-not-expose")

    with pytest.raises(TransientProviderError) as caught:
        _run_fetch(httpx.MockTransport(handler), policy=HttpPolicy(max_attempts=2))
    assert caught.value.context == {"endpoint_name": "observations", "dataset": "test_dataset"}
    assert "password" not in str(caught.value)


def test_permanent_4xx_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404, content=b"private response")

    with pytest.raises(PermanentProviderError):
        _run_fetch(httpx.MockTransport(handler))
    assert calls == 1


def test_redirect_is_rejected_without_exposing_location() -> None:
    with pytest.raises(PermanentProviderError) as caught:
        _run_fetch(
            httpx.MockTransport(
                lambda request: httpx.Response(
                    302, headers={"Location": "https://evil.test/?token=secret"}
                )
            )
        )
    assert "evil" not in str(caught.value)
    assert "token" not in repr(caught.value.context)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"12345", headers={"Content-Length": "5"}),
        httpx.Response(200, content=b"12345"),
    ],
)
def test_oversized_response_is_rejected(response: httpx.Response) -> None:
    with pytest.raises(PayloadTooLargeError):
        _run_fetch(
            httpx.MockTransport(lambda request: response),
            policy=HttpPolicy(max_response_bytes=4),
        )
