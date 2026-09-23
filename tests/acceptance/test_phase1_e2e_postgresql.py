"""One coherent offline Phase 1 scenario using production services and mocked provider I/O."""
from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.application.ingestion.orchestrator import IngestionOrchestrator, PipelineBinding
from app.application.quality.expectations import BusinessCalendar, ExpectationPolicy, ReleaseCadence
from app.application.quality.service import QualityEvaluationService
from app.application.queries.observations import ObservationQueryService
from app.database.base import Base
from app.database.models import (
    Currency, Economy, FxObservationVersion, FxObservationVersionRun, FxPair, FxSeries,
    IngestionRun, IngestionScope, InterestRateSeries, PolicyRateObservationVersion,
    ProviderDataset, QualityResult, QuarantinedRecord, RawRecord, RawResponse,
)
from app.domain.candidates import FxObservationCandidate, PolicyRateCandidate
from app.domain.enums import CanonicalRateUnit, Frequency, QuoteType, RateType
from app.domain.provider import (
    DateRange, FetchRequest, FetchResult, ParsedRecord, RawPayload, ReferenceSnapshot,
    RequestMetadata, RetryMetadata,
)
from app.domain.validation import validate_fx_candidate, validate_policy_rate_candidate
from app.repositories.quality import QualityRepository


DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is required for Phase 1 acceptance")
DAY = date(2026, 9, 18)
T1 = datetime(2026, 9, 18, 20, tzinfo=timezone.utc)
T2 = T1 + timedelta(days=1)
T3 = T2 + timedelta(days=1)


@pytest.fixture(scope="module")
def engine():
    assert DATABASE_URL and DATABASE_URL.startswith("postgresql")
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = DATABASE_URL
    migration = Config("alembic.ini")
    command.downgrade(migration, "base")
    command.upgrade(migration, "head")
    value = create_engine(DATABASE_URL)
    try:
        yield value
    finally:
        value.dispose()
        command.downgrade(migration, "base")
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest.fixture(autouse=True)
def clean_database(engine):
    with engine.begin() as connection:
        tables = ", ".join(f'"{item.name}"' for item in Base.metadata.sorted_tables)
        connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))


@dataclass(frozen=True)
class MockObservation:
    value: Decimal
    observation_date: date
    retrieved_at: datetime


class MockFetcher:
    def __init__(self, records: tuple[MockObservation, ...], retrieved_at: datetime) -> None:
        self.records = records
        self.retrieved_at = retrieved_at

    async def fetch(self, request: FetchRequest) -> FetchResult:
        body = b"|".join(f"{item.observation_date}:{item.value}".encode() for item in self.records)
        return FetchResult(
            RawPayload(body, "application/json", 200, self.retrieved_at,
                       RequestMetadata("GET", request.endpoint_name, {"start_date": request.date_range.start.isoformat()})),
            RetryMetadata(1),
        )


class MockParser:
    def __init__(self, records: tuple[MockObservation, ...]) -> None:
        self.records = records

    def parse(self, payload: RawPayload) -> tuple[ParsedRecord[MockObservation], ...]:
        del payload
        return tuple(
            ParsedRecord(item, f"observations[{index}]", hashlib.sha256(repr(item).encode()).hexdigest())
            for index, item in enumerate(self.records)
        )


class MockMapper:
    def __init__(self, series_id: UUID, kind: str) -> None:
        self.series_id = series_id
        self.kind = kind

    def map(self, record: MockObservation, source: object, mappings: ReferenceSnapshot) -> object:
        del mappings
        if self.kind == "fx":
            return FxObservationCandidate(
                self.series_id, record.observation_date, record.value, QuoteType.REFERENCE,
                record.retrieved_at, source, provider_attributes={"classification": "daily_indicative_average"},
            )
        return PolicyRateCandidate(
            self.series_id, record.observation_date, record.value,
            CanonicalRateUnit.PERCENT_PER_YEAR, Frequency.DAILY, RateType.POLICY_RATE,
            record.retrieved_at, source, provider_attributes={"collection_indicator": "main"},
        )


def _seed_references(session: Session) -> tuple[ProviderDataset, FxSeries, UUID, ProviderDataset, InterestRateSeries]:
    usd = Currency(code="USD", name="US dollar", minor_units=2, is_active=True)
    cad = Currency(code="CAD", name="Canadian dollar", minor_units=2, is_active=True)
    eur = Currency(code="EUR", name="Euro", minor_units=2, is_active=True)
    economy = Economy(code="XM", iso_country_code=None, name="Euro area", time_zone="Europe/Brussels",
                      economy_type="currency_union", is_active=True)
    fx_dataset = ProviderDataset(provider_code="bank_of_canada", dataset_code="valet_daily_fx",
        display_name="Bank of Canada", configuration_reference="fixture", approval_state="approved", is_active=True)
    bis_dataset = ProviderDataset(provider_code="bis", dataset_code="bis_policy_rates_daily",
        display_name="BIS", configuration_reference="fixture", approval_state="approved", is_active=True)
    session.add_all((usd, cad, eur, economy, fx_dataset, bis_dataset)); session.flush()
    pair = FxPair(base_currency_id=usd.id, quote_currency_id=cad.id, symbol="USDCAD", is_active=True)
    session.add(pair); session.flush()
    fx = FxSeries(provider_dataset_id=fx_dataset.id, provider_symbol="FXUSDCAD", fx_pair_id=pair.id,
                  frequency="daily", quote_type="reference", source_metadata={}, is_active=True)
    rate = InterestRateSeries(provider_dataset_id=bis_dataset.id, economy_id=economy.id, currency_id=eur.id,
        dataflow_key="WS_CBPOL", series_key="D.XM", frequency="daily", unit="percent_per_year",
        rate_type="policy_rate", collection_indicator="main", title="Euro area policy rate",
        source_metadata={}, publication_metadata={}, is_active=True)
    session.add_all((fx, rate)); session.flush()
    return fx_dataset, fx, pair.id, bis_dataset, rate


def _add_run(session: Session, dataset: ProviderDataset, kind: str, series_id: UUID,
             requested_at: datetime) -> IngestionRun:
    run = IngestionRun(trigger_type="manual", provider_dataset_id=dataset.id, requested_start=DAY - timedelta(days=1),
        requested_end=DAY, status="pending", config_checksum="a" * 64, code_version="acceptance",
        requested_at=requested_at)
    session.add(run); session.flush()
    session.add(IngestionScope(run_id=run.id, scope_type=kind, series_id=series_id,
        start_date=DAY - timedelta(days=1), end_date=DAY, attempt_number=1, status="pending"))
    session.flush()
    return run


def _execute(sessions: sessionmaker[Session], bindings: dict[UUID, PipelineBinding], now: datetime) -> UUID:
    result = asyncio.run(IngestionOrchestrator(
        sessions, code_version="acceptance", bindings=lambda run, scope: bindings[scope.series_id], now=lambda: now,
    ).run_next("acceptance-worker"))
    assert result is not None
    return result


def test_mocked_phase1_end_to_end_acceptance(engine) -> None:
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions.begin() as session:
        fx_dataset, fx, pair_id, bis_dataset, rate = _seed_references(session)
        initial_fx = _add_run(session, fx_dataset, "fx", fx.id, T1)
        fx_id, rate_id, initial_fx_id = fx.id, rate.id, initial_fx.id

    valid_fx = MockObservation(Decimal("1.25"), DAY, T1)
    invalid_fx = MockObservation(Decimal("-1"), DAY - timedelta(days=1), T1)
    initial_records = (valid_fx, invalid_fx)
    fx_binding = PipelineBinding(
        FetchRequest("valet_daily_fx", ("FXUSDCAD",), DateRange(DAY - timedelta(days=1), DAY), "mock-valet", "/mock"),
        MockFetcher(initial_records, T1), MockParser(initial_records), MockMapper(fx_id, "fx"),
        ReferenceSnapshot({}), {fx_id: "boc-fx-usdcad"},
        lambda candidate: validate_fx_candidate(candidate, base_currency="USD", quote_currency="CAD", known_series_ids=(fx_id,)),
    )
    _execute(sessions, {fx_id: fx_binding}, T1)

    with sessions.begin() as session:
        rate_dataset = session.get(ProviderDataset, bis_dataset.id)
        assert rate_dataset is not None
        policy_run = _add_run(session, rate_dataset, "policy_rate", rate_id, T1 + timedelta(minutes=1))
        policy_run_id = policy_run.id
    rate_records = (MockObservation(Decimal("4.00"), DAY, T1),)
    rate_binding = PipelineBinding(
        FetchRequest("bis_policy_rates_daily", ("D.XM",), DateRange(DAY, DAY), "mock-bis", "/mock"),
        MockFetcher(rate_records, T1), MockParser(rate_records), MockMapper(rate_id, "policy_rate"),
        ReferenceSnapshot({}), {rate_id: "bis-policy-xm"},
        lambda candidate: validate_policy_rate_candidate(candidate, known_series_ids=(rate_id,)),
    )
    _execute(sessions, {rate_id: rate_binding}, T1 + timedelta(minutes=1))

    run_ids: list[UUID] = []
    for retrieved_at, value in ((T2, Decimal("1.25")), (T3, Decimal("1.30"))):
        with sessions.begin() as session:
            dataset = session.get(ProviderDataset, fx_dataset.id)
            assert dataset is not None
            run_ids.append(_add_run(session, dataset, "fx", fx_id, retrieved_at).id)
        records = (MockObservation(value, DAY, retrieved_at),)
        binding = PipelineBinding(
            fx_binding.request, MockFetcher(records, retrieved_at), MockParser(records), MockMapper(fx_id, "fx"),
            ReferenceSnapshot({}), {fx_id: "boc-fx-usdcad"}, fx_binding.validate,
        )
        _execute(sessions, {fx_id: binding}, retrieved_at)

    with sessions.begin() as session:
        policy = ExpectationPolicy("boc-fx-usdcad", "fx_pair", "daily", "acceptance", "UTC", time(16),
            ReleaseCadence.DAILY_BUSINESS, frozenset(range(5)), timedelta(), timedelta(days=1), DAY)
        calendar = BusinessCalendar("acceptance", "1", "UTC", frozenset({5, 6}), frozenset(), DAY)
        quality = QualityEvaluationService().evaluate_and_append(
            QualityRepository(session), policy=policy, calendar=calendar, instrument_id=pair_id,
            start=DAY, end=DAY, evaluated_at=T1, available_dates={DAY}, successful_fetch_evidence=True,
            run_id=initial_fx_id,
        )
        assert quality.state.value == "complete"

    with Session(engine) as session:
        first = session.get(IngestionRun, initial_fx_id)
        policy_result = session.get(IngestionRun, policy_run_id)
        unchanged = session.get(IngestionRun, run_ids[0])
        revised = session.get(IngestionRun, run_ids[1])
        assert (first.fetched_count, first.inserted_count, first.quarantined_count) == (2, 1, 1)
        assert (policy_result.fetched_count, policy_result.inserted_count) == (1, 1)
        assert (unchanged.unchanged_count, unchanged.inserted_count) == (1, 0)
        assert (revised.revised_count, revised.inserted_count) == (1, 0)
        assert session.scalar(select(func.count()).select_from(RawResponse)) == 4
        assert session.scalar(select(func.count()).select_from(RawRecord)) == 5
        assert session.scalar(select(func.count()).select_from(QuarantinedRecord)) == 1
        assert session.scalar(select(func.count()).select_from(FxObservationVersion)) == 2
        assert session.scalar(select(func.count()).select_from(PolicyRateObservationVersion)) == 1
        first_version = session.scalar(select(FxObservationVersion).where(FxObservationVersion.version_number == 1))
        assert first_version is not None
        assert session.scalar(select(func.count()).select_from(FxObservationVersionRun).where(
            FxObservationVersionRun.observation_version_id == first_version.id)) == 2
        queries = ObservationQueryService(session)
        historical = queries.fx_latest(pair="USDCAD", as_of=T2)
        current = queries.fx_latest(pair="USDCAD", as_of=T3)
        policy_view = queries.policy_latest(series="D.XM", economy="XM", currency="EUR", as_of=T3)
        assert historical is not None and historical.value == Decimal("1.25") and historical.version_number == 1
        assert current is not None and current.value == Decimal("1.30") and current.version_number == 2
        assert current.raw_record_id and current.run_id == run_ids[1]
        assert policy_view is not None and policy_view.value == Decimal("4.00")
        assert session.scalar(select(func.count()).select_from(QualityResult).where(
            QualityResult.instrument_id == pair_id, QualityResult.quality_state == "complete")) == 1
