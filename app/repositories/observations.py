from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Generic, Protocol, Sequence, TypeVar
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.database.models import (
    FxObservation,
    FxObservationVersion,
    FxObservationVersionRun,
    PolicyRateObservation,
    PolicyRateObservationVersion,
    PolicyRateObservationVersionRun,
    RawRecord,
)
from app.domain.candidates import FxObservationCandidate, PolicyRateCandidate
from app.domain.enums import CandidateOutcome, ValidationState
from app.domain.fingerprints import fx_fingerprint, policy_rate_fingerprint
from app.domain.validation import ValidationIssue, ValidationResult


class OutOfOrderObservationError(ValueError):
    """Raised when late input would rewrite an already established knowledge timeline."""


class InvalidObservationError(ValueError):
    """Raised when a blocking validation result is sent to canonical persistence."""


@dataclass(frozen=True)
class PersistedRevision:
    outcome: CandidateOutcome
    observation_id: UUID
    version_id: UUID
    version_number: int


VersionT = TypeVar("VersionT", FxObservationVersion, PolicyRateObservationVersion)


class ObservationRepository(Protocol, Generic[VersionT]):
    def current(self, *, series_id: UUID, observation_date: date) -> VersionT | None: ...

    def as_of(
        self, *, series_id: UUID, observation_date: date, as_of: datetime
    ) -> VersionT | None: ...

    def list_history(
        self, *, series_id: UUID, start: date, end: date, as_of: datetime | None = None
    ) -> Sequence[VersionT]: ...


class FxObservationRepository(ObservationRepository[FxObservationVersion]):
    def __init__(self, session: Session) -> None:
        self.session = session

    def lock_or_create(self, series_id: UUID, observation_date: date) -> FxObservation:
        self.session.execute(
            insert(FxObservation)
            .values(fx_series_id=series_id, observation_date=observation_date)
            .on_conflict_do_nothing(constraint="uq_fx_observation_natural")
        )
        observation = self.session.scalar(
            select(FxObservation)
            .where(
                FxObservation.fx_series_id == series_id,
                FxObservation.observation_date == observation_date,
            )
            .with_for_update()
        )
        if observation is None:
            raise RuntimeError("failed to create or lock FX observation")
        return observation

    def current(self, *, series_id: UUID, observation_date: date) -> FxObservationVersion | None:
        return self.session.scalar(
            select(FxObservationVersion)
            .join(FxObservation, FxObservation.current_version_id == FxObservationVersion.id)
            .where(FxObservation.fx_series_id == series_id, FxObservation.observation_date == observation_date)
        )

    def as_of(self, *, series_id: UUID, observation_date: date, as_of: datetime) -> FxObservationVersion | None:
        return self.session.scalar(self._history_query(series_id, observation_date, observation_date, _utc(as_of)))

    def list_history(self, *, series_id: UUID, start: date, end: date, as_of: datetime | None = None) -> Sequence[FxObservationVersion]:
        return tuple(self.session.scalars(self._history_query(series_id, start, end, _utc(as_of) if as_of else None)))

    @staticmethod
    def _history_query(series_id: UUID, start: date, end: date, as_of: datetime | None) -> Select[tuple[FxObservationVersion]]:
        query = (
            select(FxObservationVersion)
            .join(FxObservation, FxObservation.id == FxObservationVersion.observation_id)
            .where(
                FxObservation.fx_series_id == series_id,
                FxObservation.observation_date.between(start, end),
            )
            .order_by(FxObservation.observation_date, FxObservation.id)
        )
        if as_of is None:
            return query.where(FxObservationVersion.valid_to.is_(None))
        return query.where(
            FxObservation.observation_date <= as_of.date(),
            FxObservationVersion.valid_from <= as_of,
            (FxObservationVersion.valid_to.is_(None)) | (FxObservationVersion.valid_to > as_of),
        )


class PolicyRateObservationRepository(ObservationRepository[PolicyRateObservationVersion]):
    def __init__(self, session: Session) -> None:
        self.session = session

    def lock_or_create(self, series_id: UUID, observation_date: date) -> PolicyRateObservation:
        self.session.execute(
            insert(PolicyRateObservation)
            .values(interest_rate_series_id=series_id, observation_date=observation_date)
            .on_conflict_do_nothing(constraint="uq_policy_rate_observation_natural")
        )
        observation = self.session.scalar(
            select(PolicyRateObservation)
            .where(
                PolicyRateObservation.interest_rate_series_id == series_id,
                PolicyRateObservation.observation_date == observation_date,
            )
            .with_for_update()
        )
        if observation is None:
            raise RuntimeError("failed to create or lock policy-rate observation")
        return observation

    def current(self, *, series_id: UUID, observation_date: date) -> PolicyRateObservationVersion | None:
        return self.session.scalar(
            select(PolicyRateObservationVersion)
            .join(PolicyRateObservation, PolicyRateObservation.current_version_id == PolicyRateObservationVersion.id)
            .where(
                PolicyRateObservation.interest_rate_series_id == series_id,
                PolicyRateObservation.observation_date == observation_date,
            )
        )

    def as_of(self, *, series_id: UUID, observation_date: date, as_of: datetime) -> PolicyRateObservationVersion | None:
        return self.session.scalar(self._history_query(series_id, observation_date, observation_date, _utc(as_of)))

    def list_history(self, *, series_id: UUID, start: date, end: date, as_of: datetime | None = None) -> Sequence[PolicyRateObservationVersion]:
        return tuple(self.session.scalars(self._history_query(series_id, start, end, _utc(as_of) if as_of else None)))

    @staticmethod
    def _history_query(series_id: UUID, start: date, end: date, as_of: datetime | None) -> Select[tuple[PolicyRateObservationVersion]]:
        query = (
            select(PolicyRateObservationVersion)
            .join(PolicyRateObservation, PolicyRateObservation.id == PolicyRateObservationVersion.observation_id)
            .where(
                PolicyRateObservation.interest_rate_series_id == series_id,
                PolicyRateObservation.observation_date.between(start, end),
            )
            .order_by(PolicyRateObservation.observation_date, PolicyRateObservation.id)
        )
        if as_of is None:
            return query.where(PolicyRateObservationVersion.valid_to.is_(None))
        return query.where(
            PolicyRateObservation.observation_date <= as_of.date(),
            PolicyRateObservationVersion.valid_from <= as_of,
            (PolicyRateObservationVersion.valid_to.is_(None)) | (PolicyRateObservationVersion.valid_to > as_of),
        )


class ObservationRevisionService:
    """Apply one validated candidate inside the caller-owned transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.fx = FxObservationRepository(session)
        self.policy_rates = PolicyRateObservationRepository(session)

    def persist_fx(
        self,
        candidate: FxObservationCandidate,
        validation: ValidationResult,
        *,
        series_stable_key: str,
        ingestion_run_id: UUID,
    ) -> PersistedRevision:
        _require_valid(validation)
        observation = self.fx.lock_or_create(candidate.series_id, candidate.observation_date)
        current = self._lock_version(FxObservationVersion, observation.current_version_id)
        fingerprint = fx_fingerprint(candidate, series_stable_key)
        flags = _flags(validation.issues)
        raw_record_id = self._raw_record_id(candidate.source.raw_response_id, candidate.source.record_path)
        version, outcome = self._apply(
            observation=observation,
            current=current,
            fingerprint=fingerprint,
            observed_at=candidate.retrieved_at,
            version_model=FxObservationVersion,
            version_values={
                "value": candidate.value,
                "quote_type": candidate.quote_type.value,
                "provider_publication_timestamp": candidate.provider_publication_timestamp,
                "validation_state": validation.state.value,
                "validation_flags": flags,
                "provider_attributes": _json(dict(candidate.provider_attributes)),
                "originating_raw_record_id": raw_record_id,
                "originating_ingestion_run_id": ingestion_run_id,
            },
        )
        self._lineage(FxObservationVersionRun, version.id, ingestion_run_id, raw_record_id, candidate.retrieved_at)
        return PersistedRevision(CandidateOutcome(outcome), observation.id, version.id, version.version_number)

    def persist_policy_rate(
        self,
        candidate: PolicyRateCandidate,
        validation: ValidationResult,
        *,
        series_stable_key: str,
        ingestion_run_id: UUID,
    ) -> PersistedRevision:
        _require_valid(validation)
        observation = self.policy_rates.lock_or_create(candidate.series_id, candidate.observation_date)
        current = self._lock_version(PolicyRateObservationVersion, observation.current_version_id)
        fingerprint = policy_rate_fingerprint(candidate, series_stable_key)
        attributes = _json(dict(candidate.provider_attributes))
        raw_record_id = self._raw_record_id(candidate.source.raw_response_id, candidate.source.record_path)
        version, outcome = self._apply(
            observation=observation,
            current=current,
            fingerprint=fingerprint,
            observed_at=candidate.retrieved_at,
            version_model=PolicyRateObservationVersion,
            version_values={
                "value": candidate.value,
                "unit": candidate.unit.value,
                "frequency": candidate.frequency.value,
                "rate_type": candidate.rate_type.value,
                "collection_indicator": str(attributes.get("collection_indicator") or "unknown"),
                "dataset_version": str(attributes["dataset_version"]) if attributes.get("dataset_version") is not None else None,
                "provider_publication_timestamp": candidate.provider_publication_timestamp,
                "validation_state": validation.state.value,
                "validation_flags": _flags(validation.issues),
                "provider_attributes": attributes,
                "originating_raw_record_id": raw_record_id,
                "originating_ingestion_run_id": ingestion_run_id,
            },
        )
        self._lineage(PolicyRateObservationVersionRun, version.id, ingestion_run_id, raw_record_id, candidate.retrieved_at)
        return PersistedRevision(CandidateOutcome(outcome), observation.id, version.id, version.version_number)

    def _apply(self, *, observation: Any, current: Any, fingerprint: str, observed_at: datetime, version_model: type[VersionT], version_values: dict[str, Any]) -> tuple[VersionT, str]:
        observed_at = _utc(observed_at)
        if current is not None and observed_at < _utc(current.valid_from):
            raise OutOfOrderObservationError("retrieval time precedes the current knowledge interval")
        if current is not None and current.version_fingerprint == fingerprint:
            current.last_observed_at = max(_utc(current.last_observed_at), observed_at)
            self.session.flush()
            return current, "unchanged"
        if current is not None and observed_at == _utc(current.valid_from):
            raise OutOfOrderObservationError("a conflicting version cannot share a knowledge timestamp")
        if current is not None:
            current.valid_to = observed_at
        version = version_model(
            observation_id=observation.id,
            version_number=1 if current is None else current.version_number + 1,
            version_fingerprint=fingerprint,
            first_observed_at=observed_at,
            last_observed_at=observed_at,
            valid_from=observed_at,
            valid_to=None,
            **version_values,
        )
        self.session.add(version)
        self.session.flush()
        observation.current_version_id = version.id
        self.session.flush()
        return version, "inserted" if current is None else "revised"

    def _raw_record_id(self, response_id: UUID, record_path: str) -> UUID:
        record_id = self.session.scalar(
            select(RawRecord.id).where(
                RawRecord.raw_response_id == response_id,
                RawRecord.record_path == record_path,
            )
        )
        if record_id is None:
            raise ValueError("candidate source does not identify a persisted raw record")
        return record_id

    def _lock_version(self, model: type[VersionT], version_id: UUID | None) -> VersionT | None:
        if version_id is None:
            return None
        return self.session.scalar(select(model).where(model.id == version_id).with_for_update())

    def _lineage(self, model: type[Any], version_id: UUID, run_id: UUID, raw_record_id: UUID, observed_at: datetime) -> None:
        existing = self.session.get(model, (version_id, run_id, raw_record_id))
        if existing is None:
            self.session.add(model(observation_version_id=version_id, ingestion_run_id=run_id, raw_record_id=raw_record_id, observed_at=observed_at))
        else:
            existing.observed_at = max(_utc(existing.observed_at), _utc(observed_at))
        self.session.flush()


def _require_valid(validation: ValidationResult) -> None:
    if validation.state is ValidationState.INVALID:
        raise InvalidObservationError("invalid candidates must be quarantined, not versioned")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("knowledge timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _json(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    if isinstance(value, (str, int, float, bool, Decimal)) or value is None:
        return str(value) if isinstance(value, Decimal) else value
    return str(value)


def _flags(issues: Sequence[ValidationIssue]) -> list[dict[str, Any]]:
    return [
        {
            "code": issue.code.value,
            "severity": issue.severity.value,
            "field": issue.field,
            "details": _json(dict(issue.details)),
        }
        for issue in issues
    ]
