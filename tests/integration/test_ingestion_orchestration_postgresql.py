"""PostgreSQL orchestration acceptance tests; provider I/O is always mocked."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.application.ingestion.orchestrator import IngestionOrchestrator, PipelineBinding
from app.database.base import Base
from app.database.models import (Currency, Economy, FxObservationVersion, FxPair, FxSeries,
    IngestionRun, IngestionScope, InterestRateSeries, PolicyRateObservationVersion,
    ProviderDataset, QuarantinedRecord, RawRecord, RawResponse)
from app.domain.candidates import FxObservationCandidate, PolicyRateCandidate
from app.domain.enums import CanonicalRateUnit, Frequency, QuoteType, RateType, ValidationSeverity, ValidationState
from app.domain.provider import DateRange, FetchRequest, FetchResult, ParsedRecord, RawPayload, ReferenceSnapshot, RequestMetadata, RetryMetadata
from app.domain.validation import ValidationCode, ValidationIssue, ValidationResult
from app.providers.base import TransientProviderError
from app.repositories.ingestion_runs import IngestionRunRepository

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is required for PostgreSQL orchestration tests")
NOW, DAY = datetime(2026, 9, 20, 20, tzinfo=timezone.utc), date(2026, 9, 19)


@pytest.fixture(scope="module")
def engine():
    assert DATABASE_URL and DATABASE_URL.startswith("postgresql")
    prior = os.environ.get("DATABASE_URL"); os.environ["DATABASE_URL"] = DATABASE_URL
    config = Config("alembic.ini"); command.downgrade(config, "base"); command.upgrade(config, "head")
    value = create_engine(DATABASE_URL)
    try: yield value
    finally:
        value.dispose(); command.downgrade(config, "base")
        if prior is None: os.environ.pop("DATABASE_URL", None)
        else: os.environ["DATABASE_URL"] = prior


@pytest.fixture(autouse=True)
def clean_database(engine):
    with engine.begin() as connection:
        tables = ", ".join(f'"{item.name}"' for item in Base.metadata.sorted_tables)
        connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))


@dataclass(frozen=True)
class Record:
    value: Decimal
    observation_date: date


class Fetcher:
    def __init__(self, count: int, fail: bool = False) -> None: self.count, self.fail = count, fail
    async def fetch(self, request: FetchRequest) -> FetchResult:
        if self.fail: raise TransientProviderError("temporary provider failure")
        body = str(self.count).encode()
        return FetchResult(RawPayload(body, "application/json", 200, NOW,
            RequestMetadata("GET", "mock", {"start_date": request.date_range.start.isoformat(), "end_date": request.date_range.end.isoformat()})), RetryMetadata(2))


class Parser:
    def __init__(self, count: int) -> None: self.count = count
    def parse(self, payload: RawPayload):
        del payload
        return tuple(ParsedRecord(Record(Decimal(i + 1), DAY - timedelta(days=i)), f"records[{i}]", hashlib.sha256(str(i).encode()).hexdigest()) for i in range(self.count))


class Mapper:
    def __init__(self, series_id: UUID, scope_type: str) -> None: self.series_id, self.scope_type = series_id, scope_type
    def map(self, record: Record, source, mappings: ReferenceSnapshot):
        del mappings
        if self.scope_type == "fx":
            return FxObservationCandidate(self.series_id, record.observation_date, record.value, QuoteType.REFERENCE, NOW, source)
        return PolicyRateCandidate(self.series_id, record.observation_date, record.value, CanonicalRateUnit.PERCENT_PER_YEAR,
            Frequency.DAILY, RateType.POLICY_RATE, NOW, source)


VALID = ValidationResult(ValidationState.VALID, ())
INVALID = ValidationResult(ValidationState.INVALID, (ValidationIssue(
    ValidationCode.RAW_NORMALIZED_MISMATCH, ValidationSeverity.ERROR, "value"),))


def seed_fx(session: Session, count: int = 1):
    suffix = uuid4().hex[:4].upper()
    base, quote = Currency(code="X" + suffix[:2], name="Base", minor_units=2, is_active=True), Currency(code="Y" + suffix[2:], name="Quote", minor_units=2, is_active=True)
    dataset = ProviderDataset(provider_code="bank_of_canada", dataset_code="valet_daily_fx", display_name="test", configuration_reference="test", approval_state="approved", is_active=True)
    session.add_all([base, quote, dataset]); session.flush()
    pair = FxPair(base_currency_id=base.id, quote_currency_id=quote.id, symbol=f"{base.code}/{quote.code}", is_active=True)
    session.add(pair); session.flush()
    series = [FxSeries(provider_dataset_id=dataset.id, provider_symbol=f"FX{suffix}{i}", fx_pair_id=pair.id, frequency="daily", quote_type="reference", source_metadata={}, is_active=True) for i in range(count)]
    session.add_all(series); session.flush(); return dataset, series


def seed_policy(session: Session):
    currency = Currency(code="Z" + uuid4().hex[:2].upper(), name="Rate", minor_units=2, is_active=True)
    economy = Economy(code=uuid4().hex, name="Economy", time_zone="UTC", economy_type="country", is_active=True)
    dataset = ProviderDataset(provider_code="bis", dataset_code="bis_policy_rates_daily", display_name="test", configuration_reference="test", approval_state="approved", is_active=True)
    session.add_all([currency, economy, dataset]); session.flush()
    series = InterestRateSeries(provider_dataset_id=dataset.id, economy_id=economy.id, currency_id=currency.id,
        dataflow_key="BIS", series_key="D.E", frequency="daily", unit="percent_per_year", rate_type="policy_rate",
        collection_indicator="M", title="Policy", source_metadata={}, publication_metadata={}, is_active=True)
    session.add(series); session.flush(); return dataset, series


def seed_run(session: Session, dataset, series, trigger="scheduled", parent=None, requested_at=NOW):
    run = IngestionRun(parent_run_id=parent, trigger_type=trigger, provider_dataset_id=dataset.id,
        requested_start=DAY-timedelta(days=2), requested_end=DAY, status="pending", config_checksum="c" * 64,
        code_version="test", requested_at=requested_at)
    session.add(run); session.flush()
    for scope_type, series_id in series:
        session.add(IngestionScope(run_id=run.id, scope_type=scope_type, series_id=series_id,
            start_date=DAY-timedelta(days=2), end_date=DAY, attempt_number=1, status="pending"))
    session.flush(); return run


def bindings(counts, failures=frozenset(), invalid=frozenset(), stable=True):
    def factory(run, scope):
        count = counts.get(scope.series_id, 0)
        return PipelineBinding(FetchRequest("test", (str(scope.series_id),), DateRange(scope.start_date, scope.end_date), "mock", "/mock"),
            Fetcher(count, scope.series_id in failures), Parser(count), Mapper(scope.series_id, scope.scope_type),
            ReferenceSnapshot({}), {scope.series_id: "stable"} if stable else {},
            lambda candidate: INVALID if scope.series_id in invalid else VALID)
    return factory


def execute(engine, factory):
    import asyncio
    sessions = sessionmaker(engine, expire_on_commit=False)
    result = asyncio.run(IngestionOrchestrator(sessions, code_version="test", bindings=factory, now=lambda: NOW).run_next("worker"))
    assert result is not None; return result


def test_full_and_empty_success_and_counter_accuracy(engine):
    with Session(engine) as session:
        dataset, series = seed_fx(session, 2); run = seed_run(session, dataset, [("fx", s.id) for s in series])
        series_ids, run_id = [item.id for item in series], run.id; session.commit()
    execute(engine, bindings({series_ids[0]: 2, series_ids[1]: 0}))
    with Session(engine) as session:
        row = session.get(IngestionRun, run_id)
        assert row.status == "succeeded"
        assert (row.fetched_count, row.inserted_count, row.unchanged_count, row.revised_count, row.quarantined_count, row.failed_count) == (2, 2, 0, 0, 0, 0)
        assert sorted(s.fetched_count for s in session.scalars(select(IngestionScope).where(IngestionScope.run_id == run_id))) == [0, 2]


def test_partial_provider_failure_preserves_successful_scope(engine):
    with Session(engine) as session:
        dataset, series = seed_fx(session, 2); run = seed_run(session, dataset, [("fx", s.id) for s in series])
        series_ids, run_id = [item.id for item in series], run.id; session.commit()
    execute(engine, bindings({item: 1 for item in series_ids}, failures={series_ids[1]}))
    with Session(engine) as session:
        row = session.get(IngestionRun, run_id)
        assert row.status == "partially_succeeded" and (row.inserted_count, row.failed_count) == (1, 1)
        assert session.scalar(select(func.count()).select_from(FxObservationVersion)) == 1


def test_quarantine_does_not_create_version(engine):
    with Session(engine) as session:
        dataset, series = seed_fx(session); run = seed_run(session, dataset, [("fx", series[0].id)])
        series_id, run_id = series[0].id, run.id; session.commit()
    execute(engine, bindings({series_id: 1}, invalid={series_id}))
    with Session(engine) as session:
        row = session.get(IngestionRun, run_id)
        assert (row.status, row.fetched_count, row.quarantined_count, row.inserted_count) == ("succeeded", 1, 1, 0)
        assert session.scalar(select(func.count()).select_from(QuarantinedRecord)) == 1
        assert session.scalar(select(func.count()).select_from(FxObservationVersion)) == 0


def test_overlap_is_skipped_without_fetch(engine):
    with Session(engine) as session:
        dataset, series = seed_fx(session)
        active = IngestionRun(trigger_type="scheduled", provider_dataset_id=dataset.id, requested_start=DAY, requested_end=DAY,
            status="running", config_checksum="a" * 64, code_version="test", requested_at=NOW-timedelta(minutes=1), started_at=NOW, heartbeat_at=NOW)
        session.add(active); session.flush(); session.add(IngestionScope(run_id=active.id, scope_type="fx", series_id=series[0].id, start_date=DAY, end_date=DAY, attempt_number=1, status="running", started_at=NOW))
        run = seed_run(session, dataset, [("fx", series[0].id)])
        series_id, run_id = series[0].id, run.id; session.commit()
    execute(engine, bindings({series_id: 1}))
    with Session(engine) as session:
        scope = session.scalar(select(IngestionScope).where(IngestionScope.run_id == run_id))
        assert session.get(IngestionRun, run_id).status == "failed" and scope.status == "skipped_conflict"
        assert session.scalar(select(func.count()).select_from(RawResponse)) == 0


def test_retry_links_new_run_and_keeps_prior_version(engine):
    with Session(engine) as session:
        dataset, series = seed_fx(session); parent = seed_run(session, dataset, [("fx", series[0].id)], requested_at=NOW-timedelta(days=1))
        dataset_id, series_id, parent_id = dataset.id, series[0].id, parent.id; session.commit()
    execute(engine, bindings({series_id: 1}))
    with Session(engine) as session:
        retry = seed_run(session, session.get(ProviderDataset, dataset_id), [("fx", series_id)], "retry", parent_id)
        retry_id = retry.id; session.commit()
    execute(engine, bindings({series_id: 1}))
    with Session(engine) as session:
        row = session.get(IngestionRun, retry_id)
        assert row.parent_run_id == parent_id and (row.unchanged_count, row.inserted_count) == (1, 0)
        assert session.scalar(select(func.count()).select_from(FxObservationVersion)) == 1
        assert session.scalar(select(func.count()).select_from(RawResponse)) == 2


def test_record_rollback_keeps_durable_raw_response(engine):
    with Session(engine) as session:
        dataset, series = seed_fx(session); run = seed_run(session, dataset, [("fx", series[0].id)])
        series_id, run_id = series[0].id, run.id; session.commit()
    execute(engine, bindings({series_id: 1}, stable=False))
    with Session(engine) as session:
        row = session.get(IngestionRun, run_id)
        assert row.status == "failed" and row.failed_count == 1
        assert session.scalar(select(func.count()).select_from(RawResponse)) == 1
        assert session.scalar(select(func.count()).select_from(RawRecord)) == 0
        assert session.scalar(select(func.count()).select_from(FxObservationVersion)) == 0


def test_same_pipeline_handles_both_provider_candidate_types(engine):
    with Session(engine) as session:
        fx_dataset, fx = seed_fx(session); fx_run = seed_run(session, fx_dataset, [("fx", fx[0].id)], requested_at=NOW-timedelta(minutes=1))
        rate_dataset, rate = seed_policy(session); rate_run = seed_run(session, rate_dataset, [("policy_rate", rate.id)])
        fx_id, rate_id, fx_run_id, rate_run_id = fx[0].id, rate.id, fx_run.id, rate_run.id; session.commit()
    factory = bindings({fx_id: 1, rate_id: 1}); execute(engine, factory); execute(engine, factory)
    with Session(engine) as session:
        assert session.get(IngestionRun, fx_run_id).status == "succeeded" and session.get(IngestionRun, rate_run_id).status == "succeeded"
        assert session.scalar(select(func.count()).select_from(FxObservationVersion)) == 1
        assert session.scalar(select(func.count()).select_from(PolicyRateObservationVersion)) == 1


def test_pending_claim_executes_postgresql_skip_locked(engine):
    with Session(engine) as session:
        dataset, series = seed_fx(session); pending = seed_run(session, dataset, [("fx", series[0].id)]); session.commit()
        claimed = IngestionRunRepository(session).claim_next("pytest", NOW)
        assert claimed is not None and claimed.id == pending.id and claimed.status == "running"
        session.rollback()
