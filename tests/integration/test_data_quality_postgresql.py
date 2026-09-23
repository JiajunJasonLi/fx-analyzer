from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.application.quality.expectations import BusinessCalendar, ExpectationPolicy, ReleaseCadence
from app.application.quality.service import QualityEvaluationService
from app.database.models import QualityResult
from app.domain.enums import QualityState
from app.repositories.quality import QualityRepository


DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is required for PostgreSQL quality tests")


@pytest.fixture
def engine():
    assert DATABASE_URL
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = DATABASE_URL
    command.downgrade(Config("alembic.ini"), "base")
    command.upgrade(Config("alembic.ini"), "head")
    value = create_engine(DATABASE_URL)
    try:
        yield value
    finally:
        value.dispose()
        command.downgrade(Config("alembic.ini"), "base")
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def test_quality_snapshots_are_append_only_and_current_is_latest(engine) -> None:
    instrument_id = uuid4()
    policy = ExpectationPolicy(
        "test-series", "fx_pair", "daily", "test-calendar", "UTC", time(16),
        ReleaseCadence.DAILY_BUSINESS, frozenset(range(5)), timedelta(), timedelta(days=1),
        date(2026, 1, 1),
    )
    calendar = BusinessCalendar(
        "test-calendar", "v1", "UTC", frozenset({5, 6}), frozenset(), date(2026, 1, 1),
    )
    service = QualityEvaluationService()
    day = date(2026, 1, 5)
    with Session(engine) as session:
        repository = QualityRepository(session)
        first = service.evaluate(
            policy=policy, calendar=calendar, instrument_id=instrument_id, start=day, end=day,
            evaluated_at=datetime(2026, 1, 5, 17, tzinfo=timezone.utc), available_dates=set(),
            successful_fetch_evidence=True,
        )
        second = service.evaluate(
            policy=policy, calendar=calendar, instrument_id=instrument_id, start=day, end=day,
            evaluated_at=datetime(2026, 1, 5, 18, tzinfo=timezone.utc), available_dates={day},
            successful_fetch_evidence=True,
        )
        repository.append_results((first, second))
        session.commit()

        rows = session.query(QualityResult).filter_by(instrument_id=instrument_id).all()
        latest = repository.latest_by_instrument(instrument_type="fx_pair", instrument_id=instrument_id)
        assert len(rows) == 2
        assert first.state is QualityState.INCOMPLETE
        assert second.state is QualityState.COMPLETE
        assert len(latest) == 1
        assert latest[0].quality_state == "complete"
        assert latest[0].evaluated_at == second.evaluated_at
