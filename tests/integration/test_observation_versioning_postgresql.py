from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.database.models import (
    Currency, FxObservation, FxObservationVersion, FxObservationVersionRun,
    FxPair, FxSeries, IngestionRun, IngestionScope, ProviderDataset, RawRecord, RawResponse,
)
from app.domain.candidates import FxObservationCandidate
from app.domain.enums import QuoteType, ValidationState
from app.domain.provider import SourceLocator
from app.domain.validation import ValidationResult
from app.repositories.observations import (
    FxObservationRepository, ObservationRevisionService, OutOfOrderObservationError,
)


DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is required for PostgreSQL versioning tests")


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


def _seed(session: Session, *, runs: int = 4) -> tuple[FxSeries, list[IngestionRun], list[RawRecord]]:
    suffix = uuid4().hex[:8].upper()
    base = Currency(code="X" + suffix[:2], name="Test base", minor_units=2, is_active=True)
    quote = Currency(code="Y" + suffix[:2], name="Test quote", minor_units=2, is_active=True)
    # Currency schema requires exactly three uppercase characters.
    base.code, quote.code = "X" + suffix[:2], "Y" + suffix[2:4]
    dataset = ProviderDataset(provider_code="bank_of_canada", dataset_code="valet_daily_fx", display_name="test", configuration_reference="test", approval_state="approved", is_active=True)
    session.add_all([base, quote, dataset]); session.flush()
    pair = FxPair(base_currency_id=base.id, quote_currency_id=quote.id, symbol=f"{base.code}/{quote.code}/{suffix}", is_active=True)
    session.add(pair); session.flush()
    series = FxSeries(provider_dataset_id=dataset.id, provider_symbol=f"FX{suffix}", fx_pair_id=pair.id, frequency="daily", quote_type="reference", source_metadata={}, is_active=True)
    session.add(series); session.flush()
    result_runs: list[IngestionRun] = []
    records: list[RawRecord] = []
    for index in range(runs):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)
        run = IngestionRun(trigger_type="manual", provider_dataset_id=dataset.id, requested_start=date(2026, 1, 1), requested_end=date(2026, 1, 1), status="running", config_checksum="c" * 64, code_version="test", requested_at=now, started_at=now, heartbeat_at=now)
        session.add(run); session.flush()
        scope = IngestionScope(run_id=run.id, scope_type="fx", series_id=series.id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 1), attempt_number=1, status="running", started_at=now)
        session.add(scope); session.flush()
        body = f"payload-{suffix}-{index}".encode()
        response = RawResponse(run_id=run.id, scope_id=scope.id, provider_dataset_id=dataset.id, endpoint_name="test", request_method="GET", request_parameters={}, retrieved_at=now, response_status=200, media_type="application/json", body=body, body_size=len(body), content_encoding=None, payload_checksum=hashlib.sha256(body).hexdigest(), response_metadata={})
        session.add(response); session.flush()
        record = RawRecord(raw_response_id=response.id, record_path="observations[0]", provider_natural_key=f"{series.provider_symbol}:2026-01-01", record_checksum=hashlib.sha256(body).hexdigest(), source_metadata={})
        session.add(record); session.flush()
        result_runs.append(run); records.append(record)
    return series, result_runs, records


def _candidate(series_id: UUID, record: RawRecord, when: datetime, value: str, *, observation_date: date = date(2026, 1, 1)) -> FxObservationCandidate:
    return FxObservationCandidate(series_id, observation_date, Decimal(value), QuoteType.REFERENCE, when, SourceLocator(record.raw_response_id, record.record_path, record.record_checksum))


def test_insert_unchanged_revision_reversion_and_as_of_boundaries(engine) -> None:
    with Session(engine) as session:
        series, runs, records = _seed(session)
        valid = ValidationResult(ValidationState.VALID, ())
        service = ObservationRevisionService(session)
        times = [datetime(2026, 1, day, 12, tzinfo=timezone.utc) for day in range(1, 5)]
        outcomes = [
            service.persist_fx(_candidate(series.id, records[0], times[0], "1.25"), valid, series_stable_key=series.provider_symbol, ingestion_run_id=runs[0].id),
            service.persist_fx(_candidate(series.id, records[1], times[1], "1.25"), valid, series_stable_key=series.provider_symbol, ingestion_run_id=runs[1].id),
            service.persist_fx(_candidate(series.id, records[2], times[2], "1.30"), valid, series_stable_key=series.provider_symbol, ingestion_run_id=runs[2].id),
            service.persist_fx(_candidate(series.id, records[3], times[3], "1.25"), valid, series_stable_key=series.provider_symbol, ingestion_run_id=runs[3].id),
        ]
        assert [item.outcome for item in outcomes] == ["inserted", "unchanged", "revised", "revised"]
        assert outcomes[0].version_id == outcomes[1].version_id
        repository = FxObservationRepository(session)
        assert repository.as_of(series_id=series.id, observation_date=date(2026, 1, 1), as_of=times[0]).value == Decimal("1.25")
        assert repository.as_of(series_id=series.id, observation_date=date(2026, 1, 1), as_of=times[2]).value == Decimal("1.30")
        assert repository.as_of(series_id=series.id, observation_date=date(2026, 1, 1), as_of=times[3]).version_number == 3
        assert repository.current(series_id=series.id, observation_date=date(2026, 1, 1)).version_number == 3
        service.persist_fx(
            _candidate(series.id, records[0], times[0], "1.40", observation_date=date(2026, 1, 10)),
            valid,
            series_stable_key=series.provider_symbol,
            ingestion_run_id=runs[0].id,
        )
        visible = repository.list_history(
            series_id=series.id,
            start=date(2026, 1, 1),
            end=date(2026, 1, 10),
            as_of=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        assert {version.observation_id for version in visible} == {outcomes[0].observation_id}
        assert session.scalar(select(func.count()).select_from(FxObservationVersion)) >= 3
        assert session.scalar(select(func.count()).select_from(FxObservationVersionRun).where(FxObservationVersionRun.observation_version_id == outcomes[0].version_id)) == 2
        with pytest.raises(OutOfOrderObservationError):
            service.persist_fx(_candidate(series.id, records[0], times[1], "1.40"), valid, series_stable_key=series.provider_symbol, ingestion_run_id=runs[0].id)
        session.rollback()


def test_concurrent_same_natural_key_has_one_current_version(engine) -> None:
    with Session(engine) as session:
        series, runs, records = _seed(session, runs=2)
        series_id = series.id
        run_ids = [run.id for run in runs]
        detached = [(record.raw_response_id, record.record_path, record.record_checksum) for record in records]
        session.commit()
    when = datetime(2026, 2, 1, 12, tzinfo=timezone.utc)

    def persist(index: int) -> str:
        with Session(engine) as session:
            locator = SourceLocator(*detached[index])
            candidate = FxObservationCandidate(series_id, date(2026, 2, 1), Decimal("1.5"), QuoteType.REFERENCE, when, locator)
            result = ObservationRevisionService(session).persist_fx(candidate, ValidationResult(ValidationState.VALID, ()), series_stable_key="concurrency", ingestion_run_id=run_ids[index])
            session.commit()
            return result.outcome

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(persist, range(2)))
    assert sorted(outcomes) == ["inserted", "unchanged"]
    with Session(engine) as session:
        observation = session.scalar(select(FxObservation).where(FxObservation.fx_series_id == series_id, FxObservation.observation_date == date(2026, 2, 1)))
        assert observation is not None
        versions = tuple(session.scalars(select(FxObservationVersion).where(FxObservationVersion.observation_id == observation.id)))
        assert len(versions) == 1
        assert versions[0].id == observation.current_version_id
