from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID

from app.domain.enums import CanonicalRateUnit, Frequency, QuoteType, RateType
from app.domain.provider import JSONValue, SourceLocator


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _immutable_attributes(value: Mapping[str, JSONValue]) -> Mapping[str, JSONValue]:
    return _freeze(value)


def _utc(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class FxObservationCandidate:
    series_id: UUID
    observation_date: date
    value: Decimal
    quote_type: QuoteType
    retrieved_at: datetime
    source: SourceLocator
    provider_publication_timestamp: datetime | None = None
    provider_attributes: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal):
            raise TypeError("value must be Decimal")
        object.__setattr__(self, "retrieved_at", _utc(self.retrieved_at, "retrieved_at"))
        object.__setattr__(
            self,
            "provider_publication_timestamp",
            _utc(self.provider_publication_timestamp, "provider_publication_timestamp"),
        )
        object.__setattr__(self, "provider_attributes", _immutable_attributes(self.provider_attributes))


@dataclass(frozen=True)
class PolicyRateCandidate:
    series_id: UUID
    observation_date: date
    value: Decimal
    unit: CanonicalRateUnit
    frequency: Frequency
    rate_type: RateType
    retrieved_at: datetime
    source: SourceLocator
    tenor: None = None
    provider_publication_timestamp: datetime | None = None
    provider_attributes: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal):
            raise TypeError("value must be Decimal")
        if self.tenor is not None:
            raise ValueError("Phase 1 policy rates have no tenor")
        object.__setattr__(self, "retrieved_at", _utc(self.retrieved_at, "retrieved_at"))
        object.__setattr__(
            self,
            "provider_publication_timestamp",
            _utc(self.provider_publication_timestamp, "provider_publication_timestamp"),
        )
        object.__setattr__(self, "provider_attributes", _immutable_attributes(self.provider_attributes))
