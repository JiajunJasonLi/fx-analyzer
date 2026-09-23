from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.application.ingestion.commands import DatasetCode, ProviderCode, StartIngestionCommand, TriggerType
from app.application.ingestion.run_manager import RunManager
from app.application.ingestion.scope_coordinator import ScopeConflictError
from app.application.queries.observations import QueryValidationError, decode_cursor, encode_cursor, validate_history_range, validate_page_size
from app.config.reference import ReferenceConfiguration
from app.database.models import (Currency, Economy, FxPair, FxSeries, IngestionRun,
                                 IngestionScope, InterestRateSeries, ProviderDataset,
                                 QualityResult, QuarantinedRecord)
from app.domain.provider import DateRange


class ResourceNotFoundError(LookupError):
    pass


class ServiceUnavailableError(RuntimeError):
    pass


class OperationsService:
    def __init__(self, session: Session, config: ReferenceConfiguration, *, code_version: str = "unknown") -> None:
        self.session = session
        self.config = config
        self.code_version = code_version

    def enqueue(self, *, provider: str, dataset: str, trigger_type: str, start: date,
                end: date, series: tuple[str, ...] | None) -> IngestionRun:
        if trigger_type == "scheduled":
            raise QueryValidationError("INVALID_TRIGGER_TYPE", "scheduled runs cannot be submitted through HTTP", field="trigger_type")
        try:
            command = StartIngestionCommand(ProviderCode(provider), DatasetCode(dataset), TriggerType(trigger_type), DateRange(start, end), series)
            run = RunManager(self.session, code_version=self.code_version).create(command, self.config)
            self.session.commit()
            return run
        except ScopeConflictError:
            self.session.rollback()
            raise
        except ValueError as exc:
            self.session.rollback()
            message = str(exc)
            if "license" in message or "approved" in message or "synchronized" in message:
                raise ServiceUnavailableError(message) from exc
            raise QueryValidationError("INVALID_INGESTION_REQUEST", message) from exc

    def run_detail(self, run_id: UUID) -> dict[str, Any]:
        run = self.session.get(IngestionRun, run_id)
        if run is None:
            raise ResourceNotFoundError("ingestion run not found")
        scopes = tuple(self.session.scalars(select(IngestionScope).where(IngestionScope.run_id == run_id).order_by(IngestionScope.id)))
        return {"run": run, "scopes": scopes}

    def list_runs(self, *, status: str | None, provider: str | None, start: date | None,
                  end: date | None, cursor: str | None, page_size: int) -> tuple[tuple[IngestionRun, str, str], str | None]:
        validate_page_size(page_size, maximum=200)
        if status is not None and status not in {"pending", "running", "succeeded", "partially_succeeded", "failed"}:
            raise QueryValidationError("INVALID_RUN_STATUS", "status is invalid", field="status")
        if provider is not None and provider not in {item.value for item in ProviderCode}:
            raise QueryValidationError("INVALID_PROVIDER", "provider is invalid", field="provider")
        if (start is None) != (end is None):
            raise QueryValidationError("INVALID_DATE_RANGE", "start_date and end_date must be supplied together")
        if start is not None and end is not None:
            validate_history_range(start, end)
        query = select(IngestionRun, ProviderDataset.provider_code, ProviderDataset.dataset_code).join(
            ProviderDataset, ProviderDataset.id == IngestionRun.provider_dataset_id
        )
        if status:
            query = query.where(IngestionRun.status == status)
        if provider:
            query = query.where(ProviderDataset.provider_code == provider)
        if start is not None and end is not None:
            query = query.where(IngestionRun.requested_start <= end, IngestionRun.requested_end >= start)
        if cursor:
            cursor_date, cursor_id = decode_cursor(cursor)
            query = query.where(or_(func.date(IngestionRun.requested_at) > cursor_date,
                                    (func.date(IngestionRun.requested_at) == cursor_date) & (IngestionRun.id > cursor_id)))
        rows = tuple(self.session.execute(query.order_by(func.date(IngestionRun.requested_at), IngestionRun.id).limit(page_size + 1)))
        visible = rows[:page_size]
        next_cursor = encode_cursor(visible[-1][0].requested_at.date(), visible[-1][0].id) if len(rows) > page_size else None
        return visible, next_cursor

    def quality(self, *, instrument_type: str | None, instrument_id: UUID | None,
                start: date | None, end: date | None) -> tuple[QualityResult, ...]:
        if instrument_type is not None and instrument_type not in {"fx_pair", "policy_rate_series"}:
            raise QueryValidationError("INVALID_INSTRUMENT_TYPE", "instrument_type is invalid", field="instrument_type")
        if instrument_id is not None and instrument_type is None:
            raise QueryValidationError("IDENTIFYING_FILTER_REQUIRED", "instrument_type is required with instrument_id", field="instrument_type")
        if (start is None) != (end is None):
            raise QueryValidationError("INVALID_DATE_RANGE", "start_date and end_date must be supplied together")
        query = select(QualityResult)
        if instrument_type:
            query = query.where(QualityResult.instrument_type == instrument_type)
        if instrument_id:
            query = query.where(QualityResult.instrument_id == instrument_id)
        if start is not None and end is not None:
            validate_history_range(start, end)
            query = query.where(QualityResult.affected_start <= end, QualityResult.affected_end >= start)
        rows = tuple(self.session.scalars(query.order_by(QualityResult.evaluated_at.desc(), QualityResult.id.desc()).limit(10000)))
        if start is not None:
            return rows
        latest: dict[tuple[str, UUID, str], QualityResult] = {}
        for row in rows:
            latest.setdefault((row.instrument_type, row.instrument_id, row.rule_code), row)
        return tuple(latest.values())

    def quarantine_counts(self, *, run_id: UUID | None, reason: str | None, stage: str | None) -> list[dict[str, Any]]:
        if stage is not None and stage not in {"parse", "map", "normalize", "validate", "conflict"}:
            raise QueryValidationError("INVALID_QUARANTINE_STAGE", "stage is invalid", field="stage")
        query = select(QuarantinedRecord.reason_code, QuarantinedRecord.stage,
                       QuarantinedRecord.resolution_state, func.count()).group_by(
            QuarantinedRecord.reason_code, QuarantinedRecord.stage, QuarantinedRecord.resolution_state
        )
        if run_id:
            query = query.where(QuarantinedRecord.run_id == run_id)
        if reason:
            query = query.where(QuarantinedRecord.reason_code == reason)
        if stage:
            query = query.where(QuarantinedRecord.stage == stage)
        return [{"reason_code": row[0], "stage": row[1], "resolution_state": row[2], "count": row[3]}
                for row in self.session.execute(query.order_by(QuarantinedRecord.reason_code, QuarantinedRecord.stage))]


def readiness(session: Session, config: ReferenceConfiguration) -> dict[str, Any]:
    checks: dict[str, bool] = {"database": False, "migrations": False, "configuration": True, "references": False}
    try:
        session.execute(text("SELECT 1"))
        checks["database"] = True
        migration = session.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar_one_or_none()
        checks["migrations"] = migration == ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
        expected_actual = (
            (sum(item.enabled for item in config.currencies), Currency),
            (sum(item.enabled for item in config.economies), Economy),
            (sum(item.enabled for item in config.fx_pairs), FxPair),
            (sum(item.enabled for item in config.provider_datasets), ProviderDataset),
            (sum(item.enabled for item in config.fx_series), FxSeries),
            (sum(item.enabled for item in config.interest_rate_series), InterestRateSeries),
        )
        checks["references"] = all(
            (session.scalar(select(func.count()).select_from(model).where(model.is_active.is_(True))) or 0) >= expected
            for expected, model in expected_actual
        )
    except Exception:
        session.rollback()
    return {"status": "ready" if all(checks.values()) else "not_ready", "checks": checks}
