from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Callable, Generic, Iterable, Mapping, Sequence, TypeVar

from app.domain.candidates import FxObservationCandidate, PolicyRateCandidate
from app.domain.enums import CanonicalRateUnit, ValidationSeverity, ValidationState
from app.domain.fingerprints import fx_fingerprint, policy_rate_fingerprint
from app.domain.provider import JSONValue


class ValidationCode(str, Enum):
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_NUMERIC_VALUE = "INVALID_NUMERIC_VALUE"
    UNKNOWN_REFERENCE = "UNKNOWN_REFERENCE"
    INVALID_OBSERVATION_DATE = "INVALID_OBSERVATION_DATE"
    RAW_NORMALIZED_MISMATCH = "RAW_NORMALIZED_MISMATCH"
    DUPLICATE_INPUT_IDENTICAL = "DUPLICATE_INPUT_IDENTICAL"
    DUPLICATE_INPUT_CONFLICT = "DUPLICATE_INPUT_CONFLICT"
    FX_NON_POSITIVE = "FX_NON_POSITIVE"
    FX_INVALID_ORIENTATION = "FX_INVALID_ORIENTATION"
    FX_OUTSIDE_PLAUSIBLE_RANGE = "FX_OUTSIDE_PLAUSIBLE_RANGE"
    FX_MOVEMENT_EXCEEDS_THRESHOLD = "FX_MOVEMENT_EXCEEDS_THRESHOLD"
    UNSUPPORTED_RATE_UNIT = "UNSUPPORTED_RATE_UNIT"
    POLICY_RATE_OUTSIDE_PLAUSIBLE_RANGE = "POLICY_RATE_OUTSIDE_PLAUSIBLE_RANGE"
    POLICY_RATE_BREAK_EXCEEDS_THRESHOLD = "POLICY_RATE_BREAK_EXCEEDS_THRESHOLD"
    OBSERVATION_STALE = "OBSERVATION_STALE"


@dataclass(frozen=True)
class ValidationIssue:
    code: ValidationCode
    severity: ValidationSeverity
    field: str | None = None
    details: Mapping[str, JSONValue] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


@dataclass(frozen=True)
class ValidationResult:
    state: ValidationState
    issues: tuple[ValidationIssue, ...]

    @classmethod
    def from_issues(cls, issues: Iterable[ValidationIssue]) -> "ValidationResult":
        ordered = tuple(issues)
        if any(issue.severity is ValidationSeverity.ERROR for issue in ordered):
            state = ValidationState.INVALID
        elif any(issue.severity is ValidationSeverity.WARNING for issue in ordered):
            state = ValidationState.VALID_WITH_WARNINGS
        else:
            state = ValidationState.VALID
        return cls(state=state, issues=ordered)


@dataclass(frozen=True)
class ValidationThresholds:
    future_tolerance: timedelta = timedelta(days=1)
    stale_after: timedelta | None = None
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    maximum_absolute_change: Decimal | None = None
    maximum_percentage_change: Decimal | None = None


@dataclass(frozen=True)
class PriorObservation:
    value: Decimal
    known_at: datetime

    def __post_init__(self) -> None:
        if self.known_at.tzinfo is None or self.known_at.utcoffset() is None:
            raise ValueError("known_at must be timezone-aware")


def _warning(code: ValidationCode, field_name: str, **details: JSONValue) -> ValidationIssue:
    return ValidationIssue(code, ValidationSeverity.WARNING, field_name, details)


def _error(code: ValidationCode, field_name: str | None, **details: JSONValue) -> ValidationIssue:
    return ValidationIssue(code, ValidationSeverity.ERROR, field_name, details)


def _temporal_issues(observation_date: date, retrieved_at: datetime, thresholds: ValidationThresholds) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    retrieval_date = retrieved_at.astimezone(timezone.utc).date()
    if observation_date > retrieval_date + thresholds.future_tolerance:
        issues.append(_error(ValidationCode.INVALID_OBSERVATION_DATE, "observation_date", future_tolerance_days=thresholds.future_tolerance.days))
    if thresholds.stale_after is not None and retrieval_date - observation_date > thresholds.stale_after:
        issues.append(_warning(ValidationCode.OBSERVATION_STALE, "observation_date", stale_after_days=thresholds.stale_after.days))
    return issues


def _range_issues(value: Decimal, thresholds: ValidationThresholds, code: ValidationCode) -> list[ValidationIssue]:
    if (thresholds.minimum is not None and value < thresholds.minimum) or (thresholds.maximum is not None and value > thresholds.maximum):
        return [_warning(code, "value", minimum=str(thresholds.minimum) if thresholds.minimum is not None else None, maximum=str(thresholds.maximum) if thresholds.maximum is not None else None)]
    return []


def _movement_issues(value: Decimal, retrieved_at: datetime, history: Iterable[PriorObservation], thresholds: ValidationThresholds, code: ValidationCode) -> list[ValidationIssue]:
    # Future knowledge must never influence an anomaly result.
    eligible = [item for item in history if item.known_at.astimezone(timezone.utc) < retrieved_at.astimezone(timezone.utc)]
    if not eligible:
        return []
    previous = max(eligible, key=lambda item: item.known_at).value
    absolute = abs(value - previous)
    percentage = None if previous == 0 else absolute / abs(previous)
    breached = thresholds.maximum_absolute_change is not None and absolute > thresholds.maximum_absolute_change
    breached = breached or (thresholds.maximum_percentage_change is not None and percentage is not None and percentage > thresholds.maximum_percentage_change)
    if not breached:
        return []
    return [_warning(code, "value", previous_value=str(previous), absolute_change=str(absolute), percentage_change=str(percentage) if percentage is not None else None)]


def validate_fx_candidate(
    candidate: FxObservationCandidate,
    *,
    base_currency: str,
    quote_currency: str,
    known_series_ids: Iterable[object],
    thresholds: ValidationThresholds = ValidationThresholds(),
    history: Iterable[PriorObservation] = (),
    raw_matches: bool = True,
) -> ValidationResult:
    issues = _temporal_issues(candidate.observation_date, candidate.retrieved_at, thresholds)
    if candidate.series_id not in set(known_series_ids):
        issues.append(_error(ValidationCode.UNKNOWN_REFERENCE, "series_id"))
    if candidate.value <= 0:
        issues.append(_error(ValidationCode.FX_NON_POSITIVE, "value"))
    if base_currency == quote_currency or quote_currency != "CAD":
        issues.append(_error(ValidationCode.FX_INVALID_ORIENTATION, "quote_currency", expected="CAD"))
    if not raw_matches:
        issues.append(_error(ValidationCode.RAW_NORMALIZED_MISMATCH, "value"))
    issues.extend(_range_issues(candidate.value, thresholds, ValidationCode.FX_OUTSIDE_PLAUSIBLE_RANGE))
    issues.extend(_movement_issues(candidate.value, candidate.retrieved_at, history, thresholds, ValidationCode.FX_MOVEMENT_EXCEEDS_THRESHOLD))
    return ValidationResult.from_issues(issues)


def validate_policy_rate_candidate(
    candidate: PolicyRateCandidate,
    *,
    known_series_ids: Iterable[object],
    thresholds: ValidationThresholds = ValidationThresholds(),
    history: Iterable[PriorObservation] = (),
    raw_matches: bool = True,
) -> ValidationResult:
    issues = _temporal_issues(candidate.observation_date, candidate.retrieved_at, thresholds)
    if candidate.series_id not in set(known_series_ids):
        issues.append(_error(ValidationCode.UNKNOWN_REFERENCE, "series_id"))
    if candidate.unit is not CanonicalRateUnit.PERCENT_PER_YEAR:
        issues.append(_error(ValidationCode.UNSUPPORTED_RATE_UNIT, "unit"))
    if not raw_matches:
        issues.append(_error(ValidationCode.RAW_NORMALIZED_MISMATCH, "value"))
    issues.extend(_range_issues(candidate.value, thresholds, ValidationCode.POLICY_RATE_OUTSIDE_PLAUSIBLE_RANGE))
    issues.extend(_movement_issues(candidate.value, candidate.retrieved_at, history, thresholds, ValidationCode.POLICY_RATE_BREAK_EXCEEDS_THRESHOLD))
    return ValidationResult.from_issues(issues)


CandidateT = TypeVar("CandidateT", FxObservationCandidate, PolicyRateCandidate)


@dataclass(frozen=True)
class DuplicateFinding(Generic[CandidateT]):
    candidate: CandidateT
    issue: ValidationIssue


def detect_batch_duplicates(
    candidates: Sequence[CandidateT],
    *,
    natural_key: Callable[[CandidateT], object],
    fingerprint: Callable[[CandidateT], str],
) -> tuple[DuplicateFinding[CandidateT], ...]:
    seen: dict[object, str] = {}
    findings: list[DuplicateFinding[CandidateT]] = []
    for candidate in candidates:
        key = natural_key(candidate)
        digest = fingerprint(candidate)
        if key in seen:
            identical = seen[key] == digest
            findings.append(DuplicateFinding(candidate, ValidationIssue(
                ValidationCode.DUPLICATE_INPUT_IDENTICAL if identical else ValidationCode.DUPLICATE_INPUT_CONFLICT,
                ValidationSeverity.INFO if identical else ValidationSeverity.ERROR,
                None,
                {"natural_key": str(key)},
            )))
        else:
            seen[key] = digest
    return tuple(findings)


def detect_fx_duplicates(candidates: Sequence[FxObservationCandidate], series_keys: Mapping[object, str]) -> tuple[DuplicateFinding[FxObservationCandidate], ...]:
    return detect_batch_duplicates(candidates, natural_key=lambda item: (item.series_id, item.observation_date), fingerprint=lambda item: fx_fingerprint(item, series_keys[item.series_id]))


def detect_policy_rate_duplicates(candidates: Sequence[PolicyRateCandidate], series_keys: Mapping[object, str]) -> tuple[DuplicateFinding[PolicyRateCandidate], ...]:
    return detect_batch_duplicates(candidates, natural_key=lambda item: (item.series_id, item.observation_date), fingerprint=lambda item: policy_rate_fingerprint(item, series_keys[item.series_id]))
