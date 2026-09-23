from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID


@dataclass(frozen=True)
class BISRecord:
    dataflow: str
    series_key: str
    economy: str
    currency: str
    frequency: str
    unit: str
    collection_indicator: str
    observation_date: date
    value: Decimal | None
    publication_timestamp: datetime | None = None
    dataset_version: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BISSeriesMapping:
    series_id: UUID
    dataflow: str
    series_key: str
    economy: str
    currency: str
    effective_from: date
    effective_to: date | None = None
    enabled: bool = True

    @property
    def complete_key(self) -> str:
        return f"{self.dataflow}:{self.series_key}"

    def applies_on(self, observation_date: date) -> bool:
        return self.effective_from <= observation_date and (
            self.effective_to is None or observation_date <= self.effective_to
        )
