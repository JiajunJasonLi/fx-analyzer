from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timezone
from typing import Any, Collection, Mapping, Protocol
from uuid import UUID

from app.domain.provider import FetchResult, SourceLocator
from app.providers.base import PayloadTooLargeError


class StoredResponse(Protocol):
    id: UUID


class StoredRecord(Protocol):
    record_path: str
    record_checksum: str | None


class RawDataRepositoryProtocol(Protocol):
    def add_response(self, **values: Any) -> StoredResponse: ...

    def get_or_create_record(
        self,
        *,
        raw_response_id: UUID,
        record_path: str,
        provider_natural_key: str | None,
        record_checksum: str | None,
        source_metadata: dict[str, Any],
    ) -> StoredRecord: ...


DEFAULT_REQUEST_PARAMETER_ALLOWLIST = frozenset(
    {"start_date", "end_date", "format", "series", "key"}
)
DEFAULT_RESPONSE_METADATA_ALLOWLIST = frozenset(
    {"content-type", "content-length", "content-encoding", "etag", "last-modified"}
)


@dataclass(frozen=True)
class RawStoragePolicy:
    max_response_bytes: int = 10 * 1024 * 1024
    request_parameter_allowlist: frozenset[str] = DEFAULT_REQUEST_PARAMETER_ALLOWLIST
    response_metadata_allowlist: frozenset[str] = DEFAULT_RESPONSE_METADATA_ALLOWLIST

    def __post_init__(self) -> None:
        if self.max_response_bytes < 1:
            raise ValueError("max_response_bytes must be positive")


class RawDataService:
    """Stores exact response bytes before a provider parser is invoked."""

    def __init__(
        self,
        repository: RawDataRepositoryProtocol,
        policy: RawStoragePolicy | None = None,
    ) -> None:
        self._repository = repository
        self._policy = policy or RawStoragePolicy()

    def store_response(
        self,
        *,
        run_id: UUID,
        scope_id: UUID,
        provider_dataset_id: UUID,
        fetch_result: FetchResult,
    ) -> UUID:
        payload = fetch_result.payload
        body_size = len(payload.body)
        if body_size > self._policy.max_response_bytes:
            raise PayloadTooLargeError(
                "provider response exceeds raw storage size limit",
                context={"endpoint_name": payload.request.endpoint_name},
            )
        if payload.request.method != "GET":
            raise ValueError("Phase 1 raw responses must use GET")
        if (
            not payload.request.endpoint_name
            or "://" in payload.request.endpoint_name
            or "?" in payload.request.endpoint_name
            or "#" in payload.request.endpoint_name
        ):
            raise ValueError("endpoint_name must be a non-empty logical name")

        request_parameters = _allowlisted_mapping(
            payload.request.sanitized_parameters,
            self._policy.request_parameter_allowlist,
        )
        response_metadata = _allowlisted_mapping(
            payload.response_metadata,
            self._policy.response_metadata_allowlist,
        )
        retrieved_at = payload.retrieved_at.astimezone(timezone.utc)
        response = self._repository.add_response(
            run_id=run_id,
            scope_id=scope_id,
            provider_dataset_id=provider_dataset_id,
            request_method=payload.request.method,
            endpoint_name=payload.request.endpoint_name,
            request_parameters=request_parameters,
            response_status=payload.response_status,
            media_type=payload.media_type,
            retrieved_at=retrieved_at,
            payload_checksum=hashlib.sha256(payload.body).hexdigest(),
            body=payload.body,
            body_size=body_size,
            content_encoding=response_metadata.get("content-encoding"),
            response_metadata=response_metadata,
        )
        return response.id

    def store_record(
        self,
        *,
        raw_response_id: UUID,
        record_path: str,
        provider_natural_key: str | None = None,
        record_checksum: str | None = None,
        source_metadata: Mapping[str, Any] | None = None,
    ) -> SourceLocator:
        if not record_path or record_path.strip() != record_path:
            raise ValueError("record_path must be a non-empty canonical path")
        if record_checksum is not None and (
            len(record_checksum) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in record_checksum)
        ):
            raise ValueError("record_checksum must be a hexadecimal SHA-256 digest")
        # Record metadata is provider-specific and is allowed only when the caller
        # explicitly supplies non-sensitive fields. Rejecting suspicious keys keeps
        # accidental credentials out while retaining interpretation metadata.
        safe_metadata = _reject_sensitive_keys(dict(source_metadata or {}))
        record = self._repository.get_or_create_record(
            raw_response_id=raw_response_id,
            record_path=record_path,
            provider_natural_key=provider_natural_key,
            record_checksum=record_checksum,
            source_metadata=safe_metadata,
        )
        return SourceLocator(
            raw_response_id=raw_response_id,
            record_path=record.record_path,
            record_checksum=record.record_checksum,
        )


def _allowlisted_mapping(
    values: Mapping[str, Any], allowlist: Collection[str]
) -> dict[str, Any]:
    allowed = {key.lower() for key in allowlist}
    return {key.lower(): value for key, value in values.items() if key.lower() in allowed}


def _reject_sensitive_keys(values: dict[str, Any]) -> dict[str, Any]:
    sensitive_fragments = ("authorization", "cookie", "credential", "password", "secret", "token")
    for key, value in values.items():
        lowered = key.lower()
        if any(fragment in lowered for fragment in sensitive_fragments):
            raise ValueError("sensitive raw-record metadata key rejected")
        if isinstance(value, Mapping):
            _reject_sensitive_keys(dict(value))
    return values
