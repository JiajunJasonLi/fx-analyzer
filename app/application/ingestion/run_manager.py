from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.ingestion.commands import StartIngestionCommand
from app.application.ingestion.scope_coordinator import ConflictPolicy, ScopeCoordinator
from app.config.reference import ReferenceConfiguration
from app.database.models import FxSeries, IngestionRun, InterestRateSeries, ProviderDataset
from app.repositories.ingestion_runs import IngestionRunRepository, IngestionScopeRepository


@dataclass(frozen=True)
class PlannedScope:
    scope_type: str
    series_id: UUID
    stable_key: str


class RunManager:
    def __init__(self, session: Session, *, code_version: str) -> None:
        self.session = session
        self.runs = IngestionRunRepository(session)
        self.scopes = IngestionScopeRepository(session)
        self.code_version = code_version

    def create(self, command: StartIngestionCommand, config: ReferenceConfiguration,
               *, requested_at: datetime | None = None) -> IngestionRun:
        command.validate(config)
        dataset = self.session.scalar(select(ProviderDataset).where(
            ProviderDataset.provider_code == command.provider.value,
            ProviderDataset.dataset_code == command.dataset.value,
        ))
        if dataset is None or not dataset.is_active or dataset.approval_state != "approved":
            raise ValueError("configured provider dataset is not synchronized and approved")
        if command.parent_run_id is not None:
            parent = self.runs.get(command.parent_run_id)
            if parent is None or parent.status not in ("succeeded", "partially_succeeded", "failed"):
                raise ValueError("retry parent must be an existing terminal run")
            if parent.provider_dataset_id != dataset.id:
                raise ValueError("retry parent belongs to a different provider dataset")
        planned_scopes = self._planned(dataset.id, command.provider.value, config)
        requested = set(command.requested_series or ())
        planned_scopes = tuple(
            item for item in planned_scopes if not requested or item.stable_key in requested
        )
        if not planned_scopes:
            raise ValueError("ingestion command has no enabled synchronized series")
        if command.trigger_type.value == "manual":
            sentinel = UUID(int=0)
            for planned in planned_scopes:
                ScopeCoordinator(self.session).claim(
                    run_id=sentinel, dataset_key=f"{command.provider.value}:{command.dataset.value}",
                    scope_type=planned.scope_type,
                    series_id=planned.series_id, start=command.date_range.start,
                    end=command.date_range.end, policy=ConflictPolicy.REJECT,
                )
        run = self.runs.add(
            parent_run_id=command.parent_run_id, trigger_type=command.trigger_type.value,
            provider_dataset_id=dataset.id, requested_start=command.date_range.start,
            requested_end=command.date_range.end, status="pending",
            config_checksum=config.checksum, code_version=self.code_version,
            requested_at=(requested_at or datetime.now(timezone.utc)).astimezone(timezone.utc),
        )
        for planned in planned_scopes:
            self.scopes.add(
                run_id=run.id, scope_type=planned.scope_type, series_id=planned.series_id,
                start_date=command.date_range.start, end_date=command.date_range.end,
                attempt_number=1, status="pending",
            )
        return run

    def derive_status(self, run_id: UUID) -> str:
        statuses = [scope.status for scope in self.scopes.list_for_run(run_id)]
        successful = statuses.count("succeeded")
        failed = statuses.count("failed")
        skipped = statuses.count("skipped_conflict")
        if any(status in ("pending", "running") for status in statuses):
            raise ValueError("cannot finalize a run with active scopes")
        if successful and (failed or skipped):
            return "partially_succeeded"
        if failed or (skipped and not successful):
            return "failed"
        return "succeeded"

    def recover_expired(self, *, heartbeat_before: datetime, now: datetime) -> tuple[UUID, ...]:
        """Fail abandoned leases without guessing whether uncommitted work succeeded."""
        expired = tuple(self.session.scalars(
            select(IngestionRun).where(
                IngestionRun.status == "running",
                IngestionRun.heartbeat_at < heartbeat_before.astimezone(timezone.utc),
            ).with_for_update(skip_locked=True)
        ))
        recovered: list[UUID] = []
        for run in expired:
            for scope in self.scopes.list_for_run(run.id):
                if scope.status in ("pending", "running"):
                    counters = {name: int(getattr(scope, name)) for name in (
                        "fetched_count", "inserted_count", "unchanged_count", "revised_count",
                        "quarantined_count", "failed_count",
                    )}
                    counters["failed_count"] += 1
                    self.scopes.complete(
                        scope.id, "failed", now, counters,
                        error_code="WORKER_LEASE_EXPIRED",
                        error_details={"message": "worker heartbeat lease expired"},
                    )
            self.runs.finalize(
                run.id, self.derive_status(run.id), now,
                error_code="WORKER_LEASE_EXPIRED",
                error_summary="worker heartbeat lease expired",
            )
            recovered.append(run.id)
        return tuple(recovered)

    def _planned(self, dataset_id: UUID, provider: str, config: ReferenceConfiguration) -> tuple[PlannedScope, ...]:
        if provider == "bank_of_canada":
            rows = {row.provider_symbol: row for row in self.session.scalars(select(FxSeries).where(FxSeries.provider_dataset_id == dataset_id, FxSeries.is_active.is_(True)))}
            return tuple(PlannedScope("fx", rows[item.provider_symbol].id, item.stable_key) for item in config.fx_series if item.enabled and item.provider_symbol in rows)
        rows = {(row.dataflow_key, row.series_key): row for row in self.session.scalars(select(InterestRateSeries).where(InterestRateSeries.provider_dataset_id == dataset_id, InterestRateSeries.is_active.is_(True)))}
        return tuple(PlannedScope("policy_rate", rows[(item.dataflow_key, item.series_key)].id, item.stable_key) for item in config.interest_rate_series if item.enabled and (item.dataflow_key, item.series_key) in rows)
