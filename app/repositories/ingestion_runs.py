from __future__ import annotations

from datetime import date, datetime, timezone
import re
from typing import Mapping
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import COUNTERS, IngestionRun, IngestionScope


ACTIVE_SCOPE_STATUSES = ("pending", "running")
TERMINAL_RUN_STATUSES = ("succeeded", "partially_succeeded", "failed")


class IngestionRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, **values: object) -> IngestionRun:
        run = IngestionRun(**values)
        self.session.add(run)
        self.session.flush()
        return run

    def get(self, run_id: UUID, *, lock: bool = False) -> IngestionRun | None:
        query = select(IngestionRun).where(IngestionRun.id == run_id)
        return self.session.scalar(query.with_for_update() if lock else query)

    def claim_next(self, worker_id: str, now: datetime) -> IngestionRun | None:
        del worker_id  # Worker identity belongs in structured logs, not the Phase 1 schema.
        run = self.session.scalar(
            select(IngestionRun)
            .where(IngestionRun.status == "pending")
            .order_by(IngestionRun.requested_at, IngestionRun.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if run is not None:
            run.status = "running"
            run.started_at = _utc(now)
            run.heartbeat_at = _utc(now)
            self.session.flush()
        return run

    def heartbeat(self, run_id: UUID, now: datetime) -> None:
        run = self._running(run_id)
        run.heartbeat_at = _utc(now)
        self.session.flush()

    def finalize(self, run_id: UUID, status: str, now: datetime, *, error_code: str | None = None, error_summary: str | None = None) -> IngestionRun:
        if status not in TERMINAL_RUN_STATUSES:
            raise ValueError("invalid terminal run status")
        run = self._running(run_id)
        totals = self.scope_totals(run_id)
        for name, value in totals.items():
            setattr(run, name, value)
        run.status = status
        run.finished_at = _utc(now)
        run.heartbeat_at = _utc(now)
        run.error_code = error_code
        run.error_summary = _sanitize(error_summary)
        self.session.flush()
        return run

    def scope_totals(self, run_id: UUID) -> dict[str, int]:
        row = self.session.execute(
            select(*(func.coalesce(func.sum(getattr(IngestionScope, name)), 0) for name in COUNTERS))
            .where(IngestionScope.run_id == run_id)
        ).one()
        return dict(zip(COUNTERS, (int(value) for value in row)))

    def _running(self, run_id: UUID) -> IngestionRun:
        run = self.get(run_id, lock=True)
        if run is None or run.status != "running":
            raise ValueError("run is not running")
        return run


class IngestionScopeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, **values: object) -> IngestionScope:
        scope = IngestionScope(**values)
        self.session.add(scope)
        self.session.flush()
        return scope

    def list_for_run(self, run_id: UUID) -> tuple[IngestionScope, ...]:
        return tuple(self.session.scalars(select(IngestionScope).where(IngestionScope.run_id == run_id).order_by(IngestionScope.id)))

    def get(self, scope_id: UUID, *, lock: bool = False) -> IngestionScope | None:
        query = select(IngestionScope).where(IngestionScope.id == scope_id)
        return self.session.scalar(query.with_for_update() if lock else query)

    def start(self, scope_id: UUID, now: datetime) -> IngestionScope:
        scope = self._status(scope_id, "pending")
        scope.status, scope.started_at = "running", _utc(now)
        self.session.flush()
        return scope

    def complete(self, scope_id: UUID, status: str, now: datetime, counters: Mapping[str, int], *, error_code: str | None = None, error_details: Mapping[str, object] | None = None, retry_count: int = 0, last_http_status: int | None = None) -> IngestionScope:
        if status not in ("succeeded", "failed", "skipped_conflict"):
            raise ValueError("invalid terminal scope status")
        scope = self.get(scope_id, lock=True)
        if scope is None or scope.status not in ACTIVE_SCOPE_STATUSES:
            raise ValueError("scope is not active")
        for name in COUNTERS:
            value = int(counters.get(name, 0))
            if value < 0:
                raise ValueError("scope counters cannot be negative")
            setattr(scope, name, value)
        scope.status, scope.finished_at = status, _utc(now)
        scope.retry_count, scope.last_http_status = retry_count, last_http_status
        scope.error_code = error_code
        scope.error_details = _sanitize_mapping(error_details)
        self.session.flush()
        return scope

    def overlaps(self, *, run_id: UUID, scope_type: str, series_id: UUID, start: date, end: date) -> bool:
        return self.session.scalar(select(IngestionScope.id).where(
            IngestionScope.run_id != run_id,
            IngestionScope.scope_type == scope_type,
            IngestionScope.series_id == series_id,
            IngestionScope.status.in_(ACTIVE_SCOPE_STATUSES),
            IngestionScope.start_date <= end,
            IngestionScope.end_date >= start,
        ).limit(1)) is not None

    def _status(self, scope_id: UUID, expected: str) -> IngestionScope:
        scope = self.get(scope_id, lock=True)
        if scope is None or scope.status != expected:
            raise ValueError(f"scope is not {expected}")
        return scope


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def _sanitize(value: str | None) -> str | None:
    if value is None:
        return None
    flattened = value.replace("\n", " ")
    flattened = re.sub(r"https?://\S+", "[redacted-url]", flattened, flags=re.IGNORECASE)
    flattened = re.sub(
        r"(?i)(authorization|cookie|credential|password|secret|token|api[_-]?key)\s*[:=]\s*\S+",
        r"\1=[redacted]",
        flattened,
    )
    return flattened[:1000]


def _sanitize_mapping(value: Mapping[str, object] | None) -> dict[str, object] | None:
    if value is None:
        return None
    forbidden = ("authorization", "cookie", "token", "password", "secret", "url")
    return {key: item for key, item in value.items() if not any(word in key.lower() for word in forbidden)}
