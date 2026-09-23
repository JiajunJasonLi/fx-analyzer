from __future__ import annotations

import hashlib
import os
import time
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, insert, text
from sqlalchemy.orm import Session

from app.application.queries.observations import ObservationQueryService
from app.database.base import Base
from app.database.models import (
    Currency, FxObservation, FxObservationVersion, FxPair, FxSeries, IngestionRun,
    IngestionScope, ProviderDataset, RawRecord, RawResponse,
)
from tests.integration.test_ingestion_orchestration_postgresql import bindings, execute, seed_fx, seed_run


DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.performance,
    pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is required for performance tests"),
]


@pytest.fixture(scope="module")
def engine():
    assert DATABASE_URL and DATABASE_URL.startswith("postgresql")
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = DATABASE_URL
    config = Config("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    value = create_engine(DATABASE_URL)
    try:
        yield value
    finally:
        value.dispose()
        command.downgrade(config, "base")
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest.fixture(autouse=True)
def clean_database(engine):
    with engine.begin() as connection:
        tables = ", ".join(f'"{item.name}"' for item in Base.metadata.sorted_tables)
        connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))


def test_twenty_year_history_first_page_is_under_two_seconds(engine) -> None:
    start = date(2006, 1, 1)
    days = 20 * 365 + 5
    observed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with Session(engine) as session:
        base = Currency(code="USD", name="US dollar", minor_units=2, is_active=True)
        quote = Currency(code="CAD", name="Canadian dollar", minor_units=2, is_active=True)
        dataset = ProviderDataset(
            provider_code="bank_of_canada", dataset_code="valet_daily_fx", display_name="performance",
            configuration_reference="test", approval_state="approved", is_active=True,
        )
        session.add_all((base, quote, dataset)); session.flush()
        pair = FxPair(base_currency_id=base.id, quote_currency_id=quote.id, symbol="USDCAD", is_active=True)
        session.add(pair); session.flush()
        series = FxSeries(provider_dataset_id=dataset.id, provider_symbol="FXUSDCAD", fx_pair_id=pair.id,
                          frequency="daily", quote_type="reference", source_metadata={}, is_active=True)
        session.add(series); session.flush()
        run = IngestionRun(trigger_type="manual", provider_dataset_id=dataset.id, requested_start=start,
                           requested_end=start + timedelta(days=days - 1), status="running",
                           config_checksum="c" * 64, code_version="performance", requested_at=observed_at,
                           started_at=observed_at, heartbeat_at=observed_at)
        session.add(run); session.flush()
        scope = IngestionScope(run_id=run.id, scope_type="fx", series_id=series.id, start_date=start,
                               end_date=start + timedelta(days=days - 1), attempt_number=1, status="running",
                               started_at=observed_at)
        session.add(scope); session.flush()
        body = b"representative-performance-fixture"
        response = RawResponse(run_id=run.id, scope_id=scope.id, provider_dataset_id=dataset.id,
            request_method="GET", endpoint_name="performance", request_parameters={}, response_status=200,
            media_type="application/json", retrieved_at=observed_at,
            payload_checksum=hashlib.sha256(body).hexdigest(), body=body, body_size=len(body),
            content_encoding=None, response_metadata={})
        session.add(response); session.flush()
        raw = RawRecord(raw_response_id=response.id, record_path="generated", provider_natural_key=None,
                        record_checksum=hashlib.sha256(body).hexdigest(), source_metadata={})
        session.add(raw); session.flush()

        observations = [(uuid4(), start + timedelta(days=index)) for index in range(days)]
        versions = [(uuid4(), observation_id, index) for index, (observation_id, _) in enumerate(observations)]
        session.execute(insert(FxObservation), [
            {"id": observation_id, "fx_series_id": series.id, "observation_date": day, "current_version_id": None}
            for observation_id, day in observations
        ])
        session.execute(insert(FxObservationVersion), [
            {"id": version_id, "observation_id": observation_id, "version_number": 1,
             "value": "1.250000000000", "quote_type": "reference", "version_fingerprint": f"{index:064x}",
             "provider_publication_timestamp": None, "first_observed_at": observed_at,
             "last_observed_at": observed_at, "valid_from": observed_at, "valid_to": None,
             "validation_state": "valid", "validation_flags": [], "provider_attributes": {},
             "originating_raw_record_id": raw.id, "originating_ingestion_run_id": run.id}
            for version_id, observation_id, index in versions
        ])
        for version_id, observation_id, _ in versions:
            session.execute(FxObservation.__table__.update().where(FxObservation.id == observation_id).values(current_version_id=version_id))
        session.commit()

        started = time.perf_counter()
        page = ObservationQueryService(session).fx_history(
            pair="USDCAD", start=start, end=start + timedelta(days=days - 1),
            as_of=datetime(2026, 9, 20, tzinfo=timezone.utc), cursor=None, page_size=500,
        )
        elapsed = time.perf_counter() - started
        assert len(page.items) == 500 and page.next_cursor is not None
        assert elapsed < 2.0, f"20-year first-page query took {elapsed:.3f}s"


def test_mocked_incremental_ingestion_is_under_fifteen_minutes(engine) -> None:
    now = datetime(2026, 9, 20, 20, tzinfo=timezone.utc)
    with Session(engine) as session:
        dataset, series = seed_fx(session)
        run = seed_run(session, dataset, [("fx", series[0].id)], requested_at=now)
        series_id = series[0].id
        session.commit()
    started = time.perf_counter()
    execute(engine, bindings({series_id: 30}))
    elapsed = time.perf_counter() - started
    assert elapsed < 15 * 60, f"mocked incremental ingestion took {elapsed:.3f}s"
