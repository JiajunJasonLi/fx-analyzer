from datetime import date
from uuid import uuid4

import pytest

from app.application.ingestion.commands import DatasetCode, ProviderCode, StartIngestionCommand, TriggerType
from app.config.reference import (
    ProviderDatasetConfig, ProviderSettingsConfig, ReferenceConfiguration,
)
from app.domain.provider import DateRange


def configuration() -> ReferenceConfiguration:
    return ReferenceConfiguration(
        currencies=(), economies=(), economy_currencies=(), fx_pairs=(), calendars=(),
        provider_datasets=(ProviderDatasetConfig(
            provider_code="bank_of_canada", dataset_code="valet_daily_fx", display_name="Valet",
            configuration_reference="test", approval_state="approved", retention_permitted=True,
            redistribution_policy="internal", settings=ProviderSettingsConfig(
                base_url="https://example.test", endpoint_template="/{series}", max_range_days=10,
            ),
        ),),
        fx_series=(), interest_rate_series=(),
    )


def command(**changes: object) -> StartIngestionCommand:
    values = dict(provider=ProviderCode.BANK_OF_CANADA, dataset=DatasetCode.VALET_DAILY_FX,
                  trigger_type=TriggerType.MANUAL,
                  date_range=DateRange(date(2026, 1, 1), date(2026, 1, 2)))
    values.update(changes)
    return StartIngestionCommand(**values)  # type: ignore[arg-type]


def test_command_accepts_bounded_approved_provider_dataset() -> None:
    command().validate(configuration())


def test_command_rejects_provider_mismatch_and_excessive_range() -> None:
    with pytest.raises(ValueError, match="do not match"):
        command(dataset=DatasetCode.BIS_POLICY_RATES_DAILY).validate(configuration())
    with pytest.raises(ValueError, match="exceeds"):
        command(date_range=DateRange(date(2026, 1, 1), date(2026, 1, 11))).validate(configuration())


def test_retry_requires_parent_and_parent_is_retry_only() -> None:
    with pytest.raises(ValueError, match="require parent"):
        command(trigger_type=TriggerType.RETRY).validate(configuration())
    with pytest.raises(ValueError, match="only for retries"):
        command(parent_run_id=uuid4()).validate(configuration())

