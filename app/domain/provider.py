from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from types import MappingProxyType
from typing import Any, Generic, Mapping, TypeVar
from uuid import UUID


# Recursive JSON aliases are represented as Any at runtime to keep imports usable
# by repository tooling that may run on Python older than the supported 3.11.
JSONValue = Any


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError("date range start must not be after end")


@dataclass(frozen=True)
class RequestMetadata:
    method: str
    endpoint_name: str
    sanitized_parameters: Mapping[str, str | list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "method", self.method.upper())
        object.__setattr__(
            self, "sanitized_parameters", MappingProxyType(dict(self.sanitized_parameters))
        )


@dataclass(frozen=True)
class RawPayload:
    body: bytes
    media_type: str
    response_status: int
    retrieved_at: datetime
    request: RequestMetadata
    response_metadata: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.retrieved_at.tzinfo is None:
            raise ValueError("retrieved_at must be timezone-aware")
        object.__setattr__(
            self, "response_metadata", MappingProxyType(dict(self.response_metadata))
        )


@dataclass(frozen=True)
class SourceLocator:
    raw_response_id: UUID
    record_path: str
    record_checksum: str | None = None


@dataclass(frozen=True)
class FetchRequest:
    dataset: str
    instruments: tuple[str, ...]
    date_range: DateRange
    endpoint_name: str
    path: str
    parameters: Mapping[str, str | list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class RetryMetadata:
    attempts: int
    retry_delays_seconds: tuple[float, ...] = ()


@dataclass(frozen=True)
class FetchResult:
    payload: RawPayload
    retry: RetryMetadata


ProviderRecordT = TypeVar("ProviderRecordT")


@dataclass(frozen=True)
class ParsedRecord(Generic[ProviderRecordT]):
    value: ProviderRecordT
    record_path: str
    record_checksum: str | None = None


@dataclass(frozen=True)
class PublishedAbsence:
    instrument: str
    observation_date: date
    reason: str
    provider_attributes: Mapping[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True)
class ReferenceSnapshot:
    """Immutable provider-to-canonical lookup values used by mappers."""

    values: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))
