from __future__ import annotations

import hashlib
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError, PendingRollbackError
from sqlalchemy.orm import Session

from app.application.ingestion.raw_data import RawDataService
from app.database.models import (
    Currency,
    FxObservation,
    FxObservationVersion,
    FxObservationVersionRun,
    FxPair,
    FxSeries,
    IngestionRun,
    IngestionScope,
    ProviderDataset,
    RawRecord,
    RawResponse,
)
from app.domain.provider import FetchResult, RawPayload, RequestMetadata, RetryMetadata
from app.repositories.raw_data import RawDataRepository


DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="TEST_DATABASE_URL is required for PostgreSQL raw-data integration tests",
)


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


def seed_scope(session: Session) -> tuple[ProviderDataset, IngestionRun, IngestionScope, FxSeries]:
    usd = Currency(code="USD", name="US Dollar", minor_units=2, is_active=True)
    cad = Currency(code="CAD", name="Canadian Dollar", minor_units=2, is_active=True)
    dataset = ProviderDataset(
        provider_code="bank_of_canada",
        dataset_code="valet_daily_fx",
        display_name="Bank of Canada daily FX",
        configuration_reference="config/reference-data.yaml",
        license_url=None,
        license_notes=None,
        attribution_text=None,
        redistribution_restrictions=None,
        approval_state="approved",
        is_active=True,
    )
    session.add_all([usd, cad, dataset])
    session.flush()
    pair = FxPair(
        base_currency_id=usd.id,
        quote_currency_id=cad.id,
        symbol="USD/CAD",
        is_active=True,
    )
    session.add(pair)
    session.flush()
    series = FxSeries(
        provider_dataset_id=dataset.id,
        provider_symbol="FXUSDCAD",
        fx_pair_id=pair.id,
        frequency="daily",
        quote_type="reference",
        source_metadata={},
        is_active=True,
    )
    run = IngestionRun(
        trigger_type="manual",
        provider_dataset_id=dataset.id,
        requested_start=date(2026, 9, 1),
        requested_end=date(2026, 9, 20),
        status="running",
        config_checksum="c" * 64,
        code_version="test",
        requested_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
        started_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
        finished_at=None,
        heartbeat_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
    )
    session.add_all([series, run])
    session.flush()
    scope = IngestionScope(
        run_id=run.id,
        scope_type="fx",
        series_id=series.id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 20),
        attempt_number=1,
        status="running",
        started_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
        finished_at=None,
    )
    session.add(scope)
    session.flush()
    return dataset, run, scope, series


def test_raw_bytes_locator_and_lineage_are_durable_and_idempotent(migrated_engine) -> None:
    body = b'\x00{"observations":{"2026-09-19":{"FXUSDCAD":{"v":"1.375"}}}}\xff'
    retrieved_at = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
    with Session(migrated_engine) as session:
        dataset, run, scope, series = seed_scope(session)
        repository = RawDataRepository(session)
        service = RawDataService(repository)
        raw_response_id = service.store_response(
            run_id=run.id,
            scope_id=scope.id,
            provider_dataset_id=dataset.id,
            fetch_result=FetchResult(
                payload=RawPayload(
                    body=body,
                    media_type="application/json",
                    response_status=200,
                    retrieved_at=retrieved_at,
                    request=RequestMetadata(
                        method="GET",
                        endpoint_name="daily-observations",
                        sanitized_parameters={"series": ["FXUSDCAD"], "token": "drop"},
                    ),
                    response_metadata={"etag": "abc", "set-cookie": "drop"},
                ),
                retry=RetryMetadata(attempts=1),
            ),
        )
        first = service.store_record(
            raw_response_id=raw_response_id,
            record_path="observations[2026-09-19].FXUSDCAD",
            provider_natural_key="FXUSDCAD:2026-09-19",
            record_checksum="a" * 64,
            source_metadata={"status": "published"},
        )
        second = service.store_record(
            raw_response_id=raw_response_id,
            record_path="observations[2026-09-19].FXUSDCAD",
            provider_natural_key="FXUSDCAD:2026-09-19",
            record_checksum="a" * 64,
            source_metadata={"status": "published"},
        )
        assert first == second

        observation = FxObservation(
            fx_series_id=series.id,
            observation_date=date(2026, 9, 19),
            current_version_id=None,
        )
        session.add(observation)
        session.flush()
        raw_record = session.scalar(
            select(RawRecord).where(RawRecord.raw_response_id == raw_response_id)
        )
        assert raw_record is not None
        version = FxObservationVersion(
            observation_id=observation.id,
            version_number=1,
            value=Decimal("1.375"),
            quote_type="reference",
            version_fingerprint="b" * 64,
            provider_publication_timestamp=None,
            first_observed_at=retrieved_at,
            last_observed_at=retrieved_at,
            valid_from=retrieved_at,
            valid_to=None,
            validation_state="valid",
            validation_flags=[],
            provider_attributes={},
            originating_raw_record_id=raw_record.id,
            originating_ingestion_run_id=run.id,
        )
        session.add(version)
        session.flush()
        observation.current_version_id = version.id
        repository.add_fx_lineage(
            observation_version_id=version.id,
            ingestion_run_id=run.id,
            raw_record_id=raw_record.id,
            observed_at=retrieved_at,
        )
        stored = session.get(RawResponse, raw_response_id)
        assert stored is not None
        assert stored.body == body
        assert stored.payload_checksum == hashlib.sha256(body).hexdigest()
        assert stored.request_parameters == {"series": ["FXUSDCAD"]}
        assert stored.response_metadata == {"etag": "abc"}
        assert session.scalar(select(RawRecord).where(RawRecord.raw_response_id == raw_response_id))
        assert session.scalar(select(FxObservationVersionRun))
        session.rollback()


def test_conflicting_duplicate_locator_rolls_back_without_changing_original(migrated_engine) -> None:
    with Session(migrated_engine) as session:
        dataset, run, scope, _series = seed_scope(session)
        repository = RawDataRepository(session)
        raw_response = repository.add_response(
            run_id=run.id,
            scope_id=scope.id,
            provider_dataset_id=dataset.id,
            request_method="GET",
            endpoint_name="daily-observations",
            request_parameters={},
            response_status=200,
            media_type="application/json",
            retrieved_at=datetime.now(timezone.utc),
            payload_checksum=hashlib.sha256(b"{}").hexdigest(),
            body=b"{}",
            body_size=2,
            content_encoding=None,
            response_metadata={},
        )
        repository.get_or_create_record(
            raw_response_id=raw_response.id,
            record_path="observations[0]",
            provider_natural_key="first",
            record_checksum=None,
            source_metadata={},
        )
        with pytest.raises(ValueError, match="different metadata"):
            repository.get_or_create_record(
                raw_response_id=raw_response.id,
                record_path="observations[0]",
                provider_natural_key="conflict",
                record_checksum=None,
                source_metadata={},
            )
        session.rollback()


def test_failed_raw_insert_cannot_be_followed_by_canonical_write(migrated_engine) -> None:
    with Session(migrated_engine) as session:
        dataset, run, scope, series = seed_scope(session)
        repository = RawDataRepository(session)
        with pytest.raises(IntegrityError):
            repository.add_response(
                run_id=run.id,
                scope_id=scope.id,
                provider_dataset_id=dataset.id,
                request_method="POST",  # violates the raw-response method constraint
                endpoint_name="daily-observations",
                request_parameters={},
                response_status=200,
                media_type="application/json",
                retrieved_at=datetime.now(timezone.utc),
                payload_checksum=hashlib.sha256(b"{}").hexdigest(),
                body=b"{}",
                body_size=2,
                content_encoding=None,
                response_metadata={},
            )
        assert not session.is_active
        with pytest.raises(PendingRollbackError):
            session.add(
                FxObservation(
                    fx_series_id=series.id,
                    observation_date=date(2026, 9, 20),
                    current_version_id=None,
                )
            )
            session.flush()
        session.rollback()
