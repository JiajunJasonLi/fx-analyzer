from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.application.quality.expectations import (
    BusinessCalendar, ExpectationPolicy, ReleaseCadence, generate_expectations,
    load_quality_configuration,
)
from app.application.quality.service import QualityEvaluationService
from app.config.reference import load_reference_configuration
from app.domain.enums import QualityState


def _calendar(*, holidays: frozenset[date] = frozenset()) -> BusinessCalendar:
    return BusinessCalendar("test", "v1", "America/Toronto", frozenset({5, 6}), holidays, date(2025, 1, 1))


def _policy(*, cadence: ReleaseCadence = ReleaseCadence.DAILY_BUSINESS, stale_days: int = 1) -> ExpectationPolicy:
    return ExpectationPolicy(
        "series", "fx_pair", "daily", "test", "America/Toronto", time(16, 30), cadence,
        frozenset({3}) if cadence is ReleaseCadence.WEEKLY else frozenset({0, 1, 2, 3, 4}),
        timedelta(hours=1), timedelta(days=stale_days), date(2025, 1, 1),
    )


def _evaluate(*, start: date, end: date, now: datetime, available: set[date], calendar: BusinessCalendar | None = None, policy: ExpectationPolicy | None = None, evidence: bool = True):
    return QualityEvaluationService().evaluate(
        policy=policy or _policy(), calendar=_calendar() if calendar is None else calendar,
        instrument_id=uuid4(), start=start, end=end, evaluated_at=now,
        available_dates=available, successful_fetch_evidence=evidence,
    )


def test_weekends_and_holidays_are_not_expected() -> None:
    holiday = date(2026, 7, 1)
    expected = generate_expectations(_policy(), _calendar(holidays=frozenset({holiday})), date(2026, 6, 27), date(2026, 7, 2))
    assert [item.observation_date for item in expected] == [date(2026, 6, 29), date(2026, 6, 30), date(2026, 7, 2)]


def test_grace_period_makes_observation_not_due() -> None:
    day = date(2026, 6, 29)
    result = _evaluate(start=day, end=day, now=datetime(2026, 6, 29, 21, 0, tzinfo=timezone.utc), available=set())
    assert result.state is QualityState.NOT_DUE


def test_complete_and_gap_evidence() -> None:
    start, end = date(2026, 6, 29), date(2026, 6, 30)
    now = datetime(2026, 7, 1, 0, tzinfo=timezone.utc)
    complete = _evaluate(start=start, end=end, now=now, available={start, end})
    incomplete = _evaluate(start=start, end=end, now=now, available={end})
    assert complete.state is QualityState.COMPLETE
    assert incomplete.state is QualityState.INCOMPLETE
    assert incomplete.details["missing_dates"] == ["2026-06-29"]


def test_old_missing_latest_due_period_is_stale() -> None:
    day = date(2026, 6, 29)
    result = _evaluate(start=day, end=day, now=datetime(2026, 7, 3, tzinfo=timezone.utc), available=set())
    assert result.state is QualityState.STALE


def test_missing_fetch_evidence_is_unknown() -> None:
    day = date(2026, 6, 29)
    result = _evaluate(start=day, end=day, now=datetime(2026, 7, 3, tzinfo=timezone.utc), available=set(), evidence=False)
    assert result.state is QualityState.UNKNOWN
    assert result.details["reason"] == "successful_fetch_evidence_missing"


def test_missing_calendar_configuration_is_unknown() -> None:
    service = QualityEvaluationService()
    result = service.evaluate(
        policy=_policy(), calendar=None, instrument_id=uuid4(), start=date(2026, 1, 1),
        end=date(2026, 1, 1), evaluated_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
        available_dates=set(), successful_fetch_evidence=True,
    )
    assert result.state is QualityState.UNKNOWN
    assert result.details["reason"] == "calendar_configuration_missing"


def test_bis_daily_observations_wait_for_weekly_release() -> None:
    policy = _policy(cadence=ReleaseCadence.WEEKLY, stale_days=7)
    expected = generate_expectations(policy, _calendar(), date(2026, 6, 29), date(2026, 6, 30))
    assert {item.observation_date for item in expected} == {date(2026, 6, 29), date(2026, 6, 30)}
    assert {item.due_at.date() for item in expected} == {date(2026, 7, 2)}
    before_release = _evaluate(
        start=date(2026, 6, 29), end=date(2026, 6, 30),
        now=datetime(2026, 7, 2, 12, tzinfo=timezone.utc), available=set(), policy=policy,
    )
    assert before_release.state is QualityState.NOT_DUE


def test_evaluation_failure_becomes_visible_unknown() -> None:
    result = QualityEvaluationService().evaluate_safely(
        policy=_policy(), calendar=_calendar(), instrument_id=uuid4(),
        start=date(2026, 2, 2), end=date(2026, 2, 1),
        evaluated_at=datetime(2026, 2, 3, tzinfo=timezone.utc),
        available_dates=set(), successful_fetch_evidence=True,
    )
    assert result.state is QualityState.UNKNOWN
    assert result.details == {
        "calendar_id": "test", "release_cadence": "daily_business",
        "expected_count": 0, "missing_count": 0, "missing_dates": [],
        "newest_expected_date": None, "newest_available_date": None,
        "reason": "quality_evaluation_failed", "error_type": "ValueError",
    }


def test_repository_configuration_has_policy_for_every_enabled_series() -> None:
    config = load_reference_configuration(Path("config/reference-data.yaml"))
    calendars, policies = load_quality_configuration(config)
    enabled = {item.stable_key for item in (*config.fx_series, *config.interest_rate_series) if item.enabled}
    assert {item.instrument_id for item in policies} == enabled
    assert all(item.calendar_id in calendars for item in policies)
