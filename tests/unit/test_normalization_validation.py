from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from app.domain.candidates import FxObservationCandidate, PolicyRateCandidate
from app.domain.enums import CanonicalRateUnit, Frequency, QuoteType, RateType, ValidationSeverity, ValidationState
from app.domain.fingerprints import canonical_decimal, canonical_json, fx_fingerprint, policy_rate_fingerprint
from app.domain.normalization import (
    NormalizationCode,
    NormalizationError,
    normalize_date,
    normalize_decimal,
    normalize_frequency,
    normalize_identifier,
    normalize_quote_type,
    normalize_rate_type,
    normalize_rate_unit,
    normalize_timestamp,
)
from app.domain.provider import SourceLocator
from app.domain.validation import (
    PriorObservation,
    ValidationCode,
    ValidationThresholds,
    detect_fx_duplicates,
    validate_fx_candidate,
    validate_policy_rate_candidate,
)


SERIES_ID = UUID("00000000-0000-0000-0000-000000000001")
RAW_ID = UUID("00000000-0000-0000-0000-000000000002")
RETRIEVED = datetime(2026, 9, 8, 15, tzinfo=timezone.utc)
SOURCE = SourceLocator(RAW_ID, "observations[0]", "a" * 64)


def fx(value: str = "1.25", **changes: object) -> FxObservationCandidate:
    values = dict(series_id=SERIES_ID, observation_date=date(2026, 9, 8), value=Decimal(value), quote_type=QuoteType.REFERENCE, retrieved_at=RETRIEVED, source=SOURCE, provider_publication_timestamp=datetime(2026, 9, 8, 10, tzinfo=timezone(timedelta(hours=-4))), provider_attributes={"status": "A", "nested": {"b": 2, "a": 1}})
    values.update(changes)
    return FxObservationCandidate(**values)  # type: ignore[arg-type]


def policy(value: str = "4.25", **changes: object) -> PolicyRateCandidate:
    values = dict(series_id=SERIES_ID, observation_date=date(2026, 9, 8), value=Decimal(value), unit=CanonicalRateUnit.PERCENT_PER_YEAR, frequency=Frequency.DAILY, rate_type=RateType.POLICY_RATE, retrieved_at=RETRIEVED, source=SOURCE, provider_attributes={"instrument": "target"})
    values.update(changes)
    return PolicyRateCandidate(**values)  # type: ignore[arg-type]


def test_normalizers_are_deterministic_and_do_not_round() -> None:
    assert normalize_identifier(" usd ", field="currency", uppercase=True) == "USD"
    assert normalize_date("2026-09-08") == date(2026, 9, 8)
    assert normalize_decimal(" 1.2300000000001 ") == Decimal("1.2300000000001")
    assert normalize_rate_unit("percent") is CanonicalRateUnit.PERCENT_PER_YEAR
    assert normalize_frequency("D") is Frequency.DAILY
    assert normalize_quote_type("REFERENCE") is QuoteType.REFERENCE
    assert normalize_rate_type("POLICY_RATE") is RateType.POLICY_RATE
    utc, original = normalize_timestamp("2026-09-08T11:30:00-04:00", field="published_at")
    assert utc == datetime(2026, 9, 8, 15, 30, tzinfo=timezone.utc)
    assert original == "2026-09-08T11:30:00-04:00"


@pytest.mark.parametrize("value", ["nan", "Infinity", "-Infinity", "not-a-number"])
def test_decimal_rejects_non_finite_and_invalid_values(value: str) -> None:
    with pytest.raises(NormalizationError) as error:
        normalize_decimal(value)
    assert error.value.code is NormalizationCode.INVALID_NUMERIC_VALUE


def test_timestamp_requires_explicit_timezone_and_candidate_normalizes_utc() -> None:
    with pytest.raises(NormalizationError) as error:
        normalize_timestamp("2026-09-08T12:00:00", field="published_at")
    assert error.value.code is NormalizationCode.INVALID_TIMESTAMP
    candidate = fx()
    assert candidate.provider_publication_timestamp == datetime(2026, 9, 8, 14, tzinfo=timezone.utc)
    with pytest.raises(TypeError):
        candidate.provider_attributes["status"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        candidate.provider_attributes["nested"]["a"] = 9  # type: ignore[index]


def test_decimal_and_json_canonicalization() -> None:
    assert canonical_decimal(Decimal("5.2500")) == "5.25"
    assert canonical_decimal(Decimal("0E-10")) == "0"
    assert canonical_json({"z": Decimal("1.0"), "a": {"y": 2, "x": 1}}) == b'{"a":{"x":1,"y":2},"z":"1"}'


def test_fx_fingerprint_is_stable_and_excludes_lineage_and_retrieval_time() -> None:
    first = fx(value="5.250", retrieved_at=RETRIEVED)
    second = fx(value="5.25", retrieved_at=RETRIEVED + timedelta(days=1), source=SourceLocator(UUID(int=3), "other"))
    assert fx_fingerprint(first, "boc:FXUSDCAD") == fx_fingerprint(second, "boc:FXUSDCAD")
    assert fx_fingerprint(first, "boc:FXUSDCAD") != fx_fingerprint(fx(provider_attributes={"status": "B"}), "boc:FXUSDCAD")
    assert fx_fingerprint(first, "boc:FXUSDCAD") != fx_fingerprint(fx(quote_type=QuoteType.REFERENCE, provider_publication_timestamp=None), "boc:FXUSDCAD")


def test_policy_fingerprint_changes_with_interpretation() -> None:
    first = policy(value="4.250")
    same = policy(value="4.25")
    changed = policy(provider_attributes={"instrument": "traded"})
    assert policy_rate_fingerprint(first, "bis:US") == policy_rate_fingerprint(same, "bis:US")
    assert policy_rate_fingerprint(first, "bis:US") != policy_rate_fingerprint(changed, "bis:US")


def test_fx_validation_errors_quarantine_and_thresholds_warn() -> None:
    candidate = fx("0", observation_date=date(2026, 9, 11))
    result = validate_fx_candidate(candidate, base_currency="USD", quote_currency="USD", known_series_ids=(), raw_matches=False, thresholds=ValidationThresholds(future_tolerance=timedelta(days=1), minimum=Decimal("0.5"), maximum=Decimal("2")))
    assert result.state is ValidationState.INVALID
    codes = {issue.code for issue in result.issues}
    assert {ValidationCode.UNKNOWN_REFERENCE, ValidationCode.FX_NON_POSITIVE, ValidationCode.FX_INVALID_ORIENTATION, ValidationCode.INVALID_OBSERVATION_DATE, ValidationCode.RAW_NORMALIZED_MISMATCH}.issubset(codes)
    assert next(issue for issue in result.issues if issue.code is ValidationCode.FX_OUTSIDE_PLAUSIBLE_RANGE).severity is ValidationSeverity.WARNING


def test_policy_plausibility_freshness_and_break_are_non_blocking() -> None:
    candidate = policy("25", observation_date=date(2026, 8, 1))
    result = validate_policy_rate_candidate(candidate, known_series_ids=(SERIES_ID,), thresholds=ValidationThresholds(stale_after=timedelta(days=7), maximum=Decimal("20"), maximum_absolute_change=Decimal("2")), history=(PriorObservation(Decimal("4"), RETRIEVED - timedelta(hours=1)),))
    assert result.state is ValidationState.VALID_WITH_WARNINGS
    assert {issue.code for issue in result.issues} == {ValidationCode.OBSERVATION_STALE, ValidationCode.POLICY_RATE_OUTSIDE_PLAUSIBLE_RANGE, ValidationCode.POLICY_RATE_BREAK_EXCEEDS_THRESHOLD}


def test_anomaly_check_uses_only_past_knowledge() -> None:
    result = validate_fx_candidate(fx("1.1"), base_currency="USD", quote_currency="CAD", known_series_ids=(SERIES_ID,), thresholds=ValidationThresholds(maximum_absolute_change=Decimal("0.5")), history=(PriorObservation(Decimal("100"), RETRIEVED + timedelta(seconds=1)), PriorObservation(Decimal("1"), RETRIEVED - timedelta(seconds=1))))
    assert result.state is ValidationState.VALID


def test_duplicate_detection_distinguishes_identical_and_conflicting() -> None:
    findings = detect_fx_duplicates((fx("1.2"), fx("1.20"), fx("1.3")), {SERIES_ID: "boc:FXUSDCAD"})
    assert [finding.issue.code for finding in findings] == [ValidationCode.DUPLICATE_INPUT_IDENTICAL, ValidationCode.DUPLICATE_INPUT_CONFLICT]
    assert [finding.issue.severity for finding in findings] == [ValidationSeverity.INFO, ValidationSeverity.ERROR]


def test_valid_candidate_has_no_issues() -> None:
    result = validate_fx_candidate(
        fx(observation_date=date(2026, 9, 9)),
        base_currency="USD",
        quote_currency="CAD",
        known_series_ids=(SERIES_ID,),
        thresholds=ValidationThresholds(
            future_tolerance=timedelta(days=1),
            minimum=Decimal("1.25"),
            maximum=Decimal("1.25"),
            maximum_absolute_change=Decimal("0.25"),
            maximum_percentage_change=Decimal("0.25"),
        ),
        history=(PriorObservation(Decimal("1.00"), RETRIEVED - timedelta(seconds=1)),),
    )
    assert result == result.from_issues(())
