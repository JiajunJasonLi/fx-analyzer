from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping
from uuid import UUID

from sqlalchemy.orm import Session

from app.database.models import QuarantinedRecord


class QuarantineRepository:
    """Persist safe diagnostics; the raw-record foreign key retains the evidence."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, *, run_id: UUID, scope_id: UUID, raw_record_id: UUID,
            reason_code: str, stage: str, now: datetime,
            provider_natural_key: str | None = None,
            details: Mapping[str, object] | None = None) -> QuarantinedRecord:
        safe = _safe_details(details or {})
        timestamp = now.astimezone(timezone.utc)
        row = QuarantinedRecord(
            run_id=run_id, scope_id=scope_id, raw_record_id=raw_record_id,
            provider_natural_key=provider_natural_key, reason_code=reason_code,
            stage=stage, details=safe, created_at=timestamp, updated_at=timestamp,
            resolution_state="unresolved",
        )
        self.session.add(row)
        self.session.flush()
        return row


def _safe_details(details: Mapping[str, object]) -> dict[str, object]:
    forbidden = ("authorization", "cookie", "credential", "password", "secret", "token", "payload", "body", "url")
    return {key: value for key, value in details.items() if not any(item in key.lower() for item in forbidden)}

