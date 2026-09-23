from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.domain.enums import ValidationSeverity, ValidationState
from app.domain.validation import ValidationCode, ValidationIssue, ValidationResult
from app.repositories.observations import (
    FxObservationRepository,
    InvalidObservationError,
    PolicyRateObservationRepository,
    _flags,
    _require_valid,
    _utc,
)


def test_invalid_candidates_are_rejected_before_persistence() -> None:
    result = ValidationResult(
        ValidationState.INVALID,
        (ValidationIssue(ValidationCode.FX_NON_POSITIVE, ValidationSeverity.ERROR, "value"),),
    )
    with pytest.raises(InvalidObservationError):
        _require_valid(result)


def test_validation_flags_are_json_safe_and_stable() -> None:
    issue = ValidationIssue(
        ValidationCode.OBSERVATION_STALE,
        ValidationSeverity.WARNING,
        "observation_date",
        {"days": 2},
    )
    assert _flags((issue,)) == [{
        "code": "OBSERVATION_STALE",
        "severity": "warning",
        "field": "observation_date",
        "details": {"days": 2},
    }]


def test_knowledge_time_requires_timezone_and_normalizes_to_utc() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _utc(datetime(2026, 1, 1))
    value = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert _utc(value) == value


@pytest.mark.parametrize(
    ("query", "table_name"),
    [
        (FxObservationRepository._history_query, "fx_observation"),
        (PolicyRateObservationRepository._history_query, "policy_rate_observation"),
    ],
)
def test_as_of_query_excludes_future_observation_dates(query, table_name) -> None:
    as_of = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
    statement = query(uuid4(), date(2026, 1, 1), date(2026, 1, 10), as_of)
    compiled = statement.compile(dialect=postgresql.dialect())
    assert f"{table_name}.observation_date <=" in str(compiled)
    assert as_of.date() in compiled.params.values()
