"""PostgreSQL atomic claim and expired-worker recovery tests."""

import os
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.application.ingestion.run_manager import RunManager
from app.database.models import IngestionRun, IngestionScope, ProviderDataset
from app.repositories.ingestion_runs import IngestionRunRepository


DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")


@pytest.fixture
def migrated_engine():
    assert DATABASE_URL is not None
    config = Config("alembic.ini")
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = DATABASE_URL
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_engine(DATABASE_URL)
    try:
        yield engine
    finally:
        engine.dispose()
        command.downgrade(config, "base")
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def test_concurrent_workers_claim_distinct_pending_runs(migrated_engine) -> None:
    with Session(migrated_engine) as setup:
        dataset = _dataset(setup)
        first = _run(dataset.id, requested_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        second = _run(dataset.id, requested_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
        setup.add_all((first, second))
        setup.commit()
        first_id, second_id = first.id, second.id

    worker_one, worker_two = Session(migrated_engine), Session(migrated_engine)
    try:
        claimed_one = IngestionRunRepository(worker_one).claim_next(
            "worker-one", datetime(2026, 1, 3, tzinfo=timezone.utc)
        )
        # Keep the first transaction/row lock open while the second worker claims.
        claimed_two = IngestionRunRepository(worker_two).claim_next(
            "worker-two", datetime(2026, 1, 3, tzinfo=timezone.utc)
        )
        assert claimed_one is not None and claimed_one.id == first_id
        assert claimed_two is not None and claimed_two.id == second_id
        worker_one.commit()
        worker_two.commit()
    finally:
        worker_one.close()
        worker_two.close()


def test_expired_lease_fails_active_work_and_allows_linked_retry(migrated_engine) -> None:
    now = datetime(2026, 1, 3, tzinfo=timezone.utc)
    with Session(migrated_engine) as session:
        dataset = _dataset(session)
        abandoned = _run(dataset.id, status="running", requested_at=now - timedelta(hours=2),
                         started_at=now - timedelta(hours=2),
                         heartbeat_at=now - timedelta(hours=1))
        session.add(abandoned)
        session.flush()
        scope = IngestionScope(
            run_id=abandoned.id, scope_type="fx", series_id=uuid4(),
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 1),
            attempt_number=1, status="running", started_at=now - timedelta(hours=2),
        )
        session.add(scope)
        session.commit()

        recovered = RunManager(session, code_version="test").recover_expired(
            heartbeat_before=now - timedelta(minutes=5), now=now
        )
        session.commit()
        assert recovered == (abandoned.id,)
        session.refresh(abandoned)
        session.refresh(scope)
        assert (abandoned.status, abandoned.error_code) == ("failed", "WORKER_LEASE_EXPIRED")
        assert (scope.status, scope.error_code, scope.failed_count) == (
            "failed", "WORKER_LEASE_EXPIRED", 1
        )

        retry = _run(dataset.id, trigger_type="retry", parent_run_id=abandoned.id,
                     requested_at=now + timedelta(seconds=1))
        session.add(retry)
        session.commit()
        assert retry.status == "pending" and retry.parent_run_id == abandoned.id


def _dataset(session: Session) -> ProviderDataset:
    dataset = ProviderDataset(
        provider_code="bank_of_canada", dataset_code="valet_daily_fx",
        display_name="test", configuration_reference="test",
        approval_state="approved", is_active=True,
    )
    session.add(dataset)
    session.flush()
    return dataset


def _run(dataset_id, *, trigger_type: str = "manual", status: str = "pending",
         requested_at: datetime, parent_run_id=None, started_at=None,
         heartbeat_at=None) -> IngestionRun:
    return IngestionRun(
        parent_run_id=parent_run_id, trigger_type=trigger_type,
        provider_dataset_id=dataset_id, requested_start=date(2026, 1, 1),
        requested_end=date(2026, 1, 1), status=status,
        config_checksum="c" * 64, code_version="test", requested_at=requested_at,
        started_at=started_at, heartbeat_at=heartbeat_at,
    )
