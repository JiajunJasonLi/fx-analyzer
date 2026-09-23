from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from app.config.reference import ReferenceConfiguration
from app.domain.provider import DateRange


class ProviderCode(str, Enum):
    BANK_OF_CANADA = "bank_of_canada"
    BIS = "bis"


class DatasetCode(str, Enum):
    VALET_DAILY_FX = "valet_daily_fx"
    BIS_POLICY_RATES_DAILY = "bis_policy_rates_daily"


class TriggerType(str, Enum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    BACKFILL = "backfill"
    RETRY = "retry"


_DATASETS = {
    ProviderCode.BANK_OF_CANADA: DatasetCode.VALET_DAILY_FX,
    ProviderCode.BIS: DatasetCode.BIS_POLICY_RATES_DAILY,
}


@dataclass(frozen=True)
class StartIngestionCommand:
    provider: ProviderCode
    dataset: DatasetCode
    trigger_type: TriggerType
    date_range: DateRange
    requested_series: tuple[str, ...] | None = None
    parent_run_id: UUID | None = None

    def validate(self, config: ReferenceConfiguration) -> None:
        if _DATASETS[self.provider] is not self.dataset:
            raise ValueError("provider and dataset do not match")
        dataset_key = f"{self.provider.value}:{self.dataset.value}"
        config.assert_ingestion_allowed(dataset_key)
        dataset = next(item for item in config.provider_datasets if item.key == dataset_key)
        maximum = dataset.settings.max_range_days if dataset.settings else 366
        if (self.date_range.end - self.date_range.start).days + 1 > maximum:
            raise ValueError("requested date range exceeds configured maximum")
        available = {
            item.stable_key
            for item in (*config.fx_series, *config.interest_rate_series)
            if item.dataset == dataset_key and item.enabled
        }
        requested = tuple(dict.fromkeys(self.requested_series or ()))
        unknown = set(requested) - available
        if unknown:
            raise ValueError(f"unknown or disabled requested series: {', '.join(sorted(unknown))}")
        if self.trigger_type is TriggerType.RETRY and self.parent_run_id is None:
            raise ValueError("retry commands require parent_run_id")
        if self.trigger_type is not TriggerType.RETRY and self.parent_run_id is not None:
            raise ValueError("parent_run_id is valid only for retries")

