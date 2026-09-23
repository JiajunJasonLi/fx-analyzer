from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.ingestion.commands import (
    DatasetCode,
    ProviderCode,
    StartIngestionCommand,
    TriggerType,
)
from app.application.ingestion.run_manager import RunManager
from app.application.quality.expectations import (
    BusinessCalendar,
    ExpectationPolicy,
    ReleaseCadence,
    generate_expectations,
    load_quality_configuration,
)
from app.config.reference import ReferenceConfiguration
from app.database.models import IngestionRun, ProviderDataset
from app.domain.provider import DateRange


@dataclass(frozen=True)
class ScheduledCommand:
    command: StartIngestionCommand
    due_at: datetime
    evaluated_at: datetime
    reason_code: str


class CommandSink(Protocol):
    def submit(self, scheduled: ScheduledCommand) -> bool: ...


class SchedulerPlanner:
    """Convert configured publication policies into provider-level commands."""

    def __init__(self, configuration: ReferenceConfiguration) -> None:
        self.configuration = configuration
        self.calendars, self.policies = load_quality_configuration(configuration)

    def due_commands(self, now: datetime) -> tuple[ScheduledCommand, ...]:
        now = _utc(now)
        commands: list[ScheduledCommand] = []
        for provider, dataset, instrument_type in (
            (ProviderCode.BANK_OF_CANADA, DatasetCode.VALET_DAILY_FX, "fx_pair"),
            (ProviderCode.BIS, DatasetCode.BIS_POLICY_RATES_DAILY, "policy_rate_series"),
        ):
            dataset_key = f"{provider.value}:{dataset.value}"
            configured_dataset = next(
                (item for item in self.configuration.provider_datasets if item.key == dataset_key), None
            )
            if (configured_dataset is None or not configured_dataset.enabled
                    or configured_dataset.approval_state != "approved"
                    or not configured_dataset.retention_permitted):
                continue
            policies = tuple(item for item in self.policies if item.instrument_type == instrument_type)
            if not policies:
                continue
            representative = policies[0]
            calendar = self.calendars[representative.calendar_id]
            due = self._latest_due(representative, calendar, now)
            if due is None:
                continue
            observation_date, due_at = due
            start = observation_date
            if representative.release_cadence is ReleaseCadence.WEEKLY:
                start = observation_date - timedelta(days=6)
            commands.append(ScheduledCommand(
                StartIngestionCommand(
                    provider=provider,
                    dataset=dataset,
                    trigger_type=TriggerType.SCHEDULED,
                    date_range=DateRange(start, observation_date),
                ),
                due_at,
                now,
                "PUBLICATION_WINDOW_DUE",
            ))
        return tuple(commands)

    @staticmethod
    def _latest_due(
        policy: ExpectationPolicy, calendar: BusinessCalendar, now: datetime
    ) -> tuple[date, datetime] | None:
        local_date = now.astimezone(ZoneInfo(policy.publication_time_zone)).date()
        search_start = max(policy.effective_from, local_date - timedelta(days=14))
        candidates = generate_expectations(policy, calendar, search_start, local_date)
        due = [item for item in candidates if item.due_at <= now]
        if not due:
            return None
        latest_due_at = max(item.due_at for item in due)
        # Weekly publication releases the daily observations through its release date.
        released = [item.observation_date for item in due if item.due_at == latest_due_at]
        return max(released), latest_due_at


class DatabaseCommandSink:
    """Create a pending run unless an active/equivalent successful run covers it."""

    def __init__(self, session: Session, configuration: ReferenceConfiguration, *, code_version: str) -> None:
        self.session = session
        self.configuration = configuration
        self.code_version = code_version

    def submit(self, scheduled: ScheduledCommand) -> bool:
        command = scheduled.command
        dataset = self.session.scalar(select(ProviderDataset).where(
            ProviderDataset.provider_code == command.provider.value,
            ProviderDataset.dataset_code == command.dataset.value,
        ))
        if dataset is None:
            raise ValueError("scheduled provider dataset has not been synchronized")
        duplicate = self.session.scalar(select(IngestionRun.id).where(
            IngestionRun.provider_dataset_id == dataset.id,
            IngestionRun.status.in_(("pending", "running", "succeeded")),
            IngestionRun.requested_start <= command.date_range.start,
            IngestionRun.requested_end >= command.date_range.end,
        ).limit(1))
        if duplicate is not None:
            return False
        RunManager(self.session, code_version=self.code_version).create(
            command, self.configuration, requested_at=scheduled.evaluated_at
        )
        return True


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("scheduler clock must return a timezone-aware timestamp")
    return value.astimezone(timezone.utc)
