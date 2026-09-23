from __future__ import annotations

import hashlib
from datetime import date
from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.repositories.ingestion_runs import IngestionScopeRepository


class ConflictPolicy(str, Enum):
    REJECT = "reject"
    SKIP = "skip"


class ScopeConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScopeClaim:
    acquired: bool
    reason: str | None = None


class ScopeCoordinator:
    """Serialize overlap checks with a stable PostgreSQL transaction lock."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.scopes = IngestionScopeRepository(session)

    def claim(self, *, run_id: UUID, dataset_key: str, scope_type: str,
              series_id: UUID, start: date, end: date,
              policy: ConflictPolicy) -> ScopeClaim:
        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            key = _advisory_key(f"{dataset_key}:{scope_type}:{series_id}")
            self.session.execute(select(func.pg_advisory_xact_lock(key))).scalar_one()
        overlap = self.scopes.overlaps(
            run_id=run_id, scope_type=scope_type, series_id=series_id,
            start=start, end=end,
        )
        if not overlap:
            return ScopeClaim(True)
        if policy is ConflictPolicy.REJECT:
            raise ScopeConflictError("an active ingestion scope overlaps the requested range")
        return ScopeClaim(False, "OVERLAPPING_ACTIVE_SCOPE")


def _advisory_key(value: str) -> int:
    return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big", signed=True)
