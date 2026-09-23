from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.quality.service import QualityAssessment
from app.database.models import (
    FxObservation, FxObservationVersion, PolicyRateObservation,
    PolicyRateObservationVersion, QualityResult,
)


class QualityRepository:
    """Persistence and as-of evidence queries for quality evaluation."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def append_results(self, results: Sequence[QualityAssessment]) -> None:
        for result in results:
            self.session.add(QualityResult(
                run_id=result.run_id, instrument_type=result.instrument_type,
                instrument_id=result.instrument_id, rule_code=result.rule_code,
                quality_state=result.state.value, severity=result.severity.value,
                affected_start=result.affected_start, affected_end=result.affected_end,
                evaluated_at=_utc(result.evaluated_at), details=dict(result.details),
            ))
        self.session.flush()

    def latest_by_instrument(
        self, *, instrument_type: str | None = None, instrument_id: UUID | None = None,
    ) -> tuple[QualityResult, ...]:
        query = select(QualityResult)
        if instrument_type is not None:
            query = query.where(QualityResult.instrument_type == instrument_type)
        if instrument_id is not None:
            query = query.where(QualityResult.instrument_id == instrument_id)
        rows = self.session.scalars(query.order_by(QualityResult.evaluated_at.desc(), QualityResult.id.desc()))
        latest: dict[tuple[str, UUID, str], QualityResult] = {}
        for row in rows:
            latest.setdefault((row.instrument_type, row.instrument_id, row.rule_code), row)
        return tuple(latest.values())

    def valid_fx_dates(self, *, series_id: UUID, start: date, end: date, as_of: datetime) -> set[date]:
        instant = _utc(as_of)
        return set(self.session.scalars(
            select(FxObservation.observation_date)
            .join(FxObservationVersion, FxObservationVersion.observation_id == FxObservation.id)
            .where(
                FxObservation.fx_series_id == series_id,
                FxObservation.observation_date.between(start, end),
                FxObservation.observation_date <= instant.date(),
                FxObservationVersion.valid_from <= instant,
                (FxObservationVersion.valid_to.is_(None)) | (FxObservationVersion.valid_to > instant),
                FxObservationVersion.validation_state.in_(("valid", "valid_with_warnings")),
            )
        ))

    def valid_policy_rate_dates(self, *, series_id: UUID, start: date, end: date, as_of: datetime) -> set[date]:
        instant = _utc(as_of)
        return set(self.session.scalars(
            select(PolicyRateObservation.observation_date)
            .join(PolicyRateObservationVersion, PolicyRateObservationVersion.observation_id == PolicyRateObservation.id)
            .where(
                PolicyRateObservation.interest_rate_series_id == series_id,
                PolicyRateObservation.observation_date.between(start, end),
                PolicyRateObservation.observation_date <= instant.date(),
                PolicyRateObservationVersion.valid_from <= instant,
                (PolicyRateObservationVersion.valid_to.is_(None)) | (PolicyRateObservationVersion.valid_to > instant),
                PolicyRateObservationVersion.validation_state.in_(("valid", "valid_with_warnings")),
            )
        ))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return value.astimezone(timezone.utc)
