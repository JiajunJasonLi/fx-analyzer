from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.application.ingestion.raw_data import RawDataService
from app.application.ingestion.run_manager import RunManager
from app.application.ingestion.scope_coordinator import ConflictPolicy, ScopeConflictError, ScopeCoordinator
from app.database.models import COUNTERS, IngestionRun, IngestionScope, RawRecord
from app.domain.candidates import FxObservationCandidate, PolicyRateCandidate
from app.domain.enums import CandidateOutcome, ValidationState
from app.domain.provider import FetchRequest, FetchResult, ParsedRecord, PublishedAbsence, ReferenceSnapshot
from app.domain.validation import ValidationResult
from app.repositories.ingestion_runs import IngestionRunRepository, IngestionScopeRepository
from app.repositories.observations import ObservationRevisionService
from app.repositories.quarantine import QuarantineRepository
from app.repositories.raw_data import RawDataRepository
from app.observability.metrics import metrics


LOGGER = logging.getLogger("fx_analyzer.ingestion")


class Fetcher(Protocol):
    async def fetch(self, request: FetchRequest) -> FetchResult: ...


class Parser(Protocol):
    def parse(self, payload: Any) -> Iterable[ParsedRecord[Any]]: ...


class Mapper(Protocol):
    def map(self, record: Any, source: Any, mappings: ReferenceSnapshot) -> Any: ...


@dataclass(frozen=True)
class PipelineBinding:
    request: FetchRequest
    fetcher: Fetcher
    parser: Parser
    mapper: Mapper
    mappings: ReferenceSnapshot
    stable_keys: Mapping[UUID, str]
    validate: Callable[[FxObservationCandidate | PolicyRateCandidate], ValidationResult]
    quality_trigger: Callable[[UUID, UUID], None] | None = None


@dataclass(frozen=True)
class ScopeResult:
    counters: Mapping[str, int]
    retry_count: int = 0
    last_http_status: int | None = None


class SharedIngestionPipeline:
    """One raw-first record pipeline shared by both provider-specific adapters."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    async def execute(self, *, run: IngestionRun, scope: IngestionScope,
                      binding: PipelineBinding) -> ScopeResult:
        provider = "bank_of_canada" if scope.scope_type == "fx" else "bis"
        request_started = time.perf_counter()
        try:
            fetched = await binding.fetcher.fetch(binding.request)
        except Exception:
            metrics.increment("fx_analyzer_provider_requests_total", provider=provider, outcome="failed", status_class="error")
            raise
        metrics.observe("fx_analyzer_provider_request_duration_seconds", time.perf_counter() - request_started, provider=provider)
        metrics.increment("fx_analyzer_provider_requests_total", provider=provider, outcome="succeeded",
                          status_class=f"{fetched.payload.response_status // 100}xx")
        if fetched.retry.attempts > 1:
            metrics.increment("fx_analyzer_provider_retries_total", fetched.retry.attempts - 1,
                              provider=provider, reason="transient")
        # The successful response is durable before parsing begins.
        with self.sessions.begin() as session:
            raw_response_id = RawDataService(RawDataRepository(session)).store_response(
                run_id=run.id, scope_id=scope.id,
                provider_dataset_id=run.provider_dataset_id, fetch_result=fetched,
            )
        parsed = tuple(binding.parser.parse(fetched.payload))
        counts = _empty_counts()
        counts["fetched_count"] = len(parsed)
        for item in parsed:
            self._process_record(run.id, scope.id, raw_response_id, item, binding, counts)
        if binding.quality_trigger is not None:
            binding.quality_trigger(run.id, scope.id)
        return ScopeResult(counts, max(0, fetched.retry.attempts - 1), fetched.payload.response_status)

    def _process_record(self, run_id: UUID, scope_id: UUID, response_id: UUID,
                        item: ParsedRecord[Any], binding: PipelineBinding,
                        counts: dict[str, int]) -> None:
        with self.sessions.begin() as session:
            raw_service = RawDataService(RawDataRepository(session))
            source = raw_service.store_record(
                raw_response_id=response_id, record_path=item.record_path,
                record_checksum=item.record_checksum,
            )
            raw_record = session.query(RawRecord).filter_by(
                raw_response_id=response_id, record_path=item.record_path
            ).one()
            try:
                candidate = binding.mapper.map(item.value, source, binding.mappings)
            except Exception as exc:
                QuarantineRepository(session).add(
                    run_id=run_id, scope_id=scope_id, raw_record_id=raw_record.id,
                    reason_code=_reason(exc), stage="map", now=datetime.now(timezone.utc),
                    details={"record_path": item.record_path},
                )
                counts["quarantined_count"] += 1
                metrics.increment("fx_analyzer_quarantined_records_total", provider=_provider(binding), reason=_reason(exc))
                return
            if isinstance(candidate, PublishedAbsence):
                return
            validation = binding.validate(candidate)
            if validation.state is ValidationState.INVALID:
                QuarantineRepository(session).add(
                    run_id=run_id, scope_id=scope_id, raw_record_id=raw_record.id,
                    reason_code=validation.issues[0].code.value if validation.issues else "INVALID_RECORD",
                    stage="validate", now=datetime.now(timezone.utc),
                    details={"record_path": item.record_path,
                             "reason_codes": [issue.code.value for issue in validation.issues]},
                )
                counts["quarantined_count"] += 1
                metrics.increment("fx_analyzer_quarantined_records_total", provider=_provider(binding), reason="validation")
                return
            revision = ObservationRevisionService(session)
            stable_key = binding.stable_keys[candidate.series_id]
            if isinstance(candidate, FxObservationCandidate):
                persisted = revision.persist_fx(candidate, validation, series_stable_key=stable_key, ingestion_run_id=run_id)
            elif isinstance(candidate, PolicyRateCandidate):
                persisted = revision.persist_policy_rate(candidate, validation, series_stable_key=stable_key, ingestion_run_id=run_id)
            else:
                raise TypeError("provider mapper returned an unsupported candidate")
            counts[f"{persisted.outcome.value}_count"] += 1


class IngestionOrchestrator:
    def __init__(self, sessions: sessionmaker[Session], *, code_version: str,
                 bindings: Callable[[IngestionRun, IngestionScope], PipelineBinding],
                 now: Callable[[], datetime] | None = None,
                 heartbeat_interval: float = 30.0) -> None:
        self.sessions = sessions
        self.code_version = code_version
        self.bindings = bindings
        self.now = now or (lambda: datetime.now(timezone.utc))
        if heartbeat_interval <= 0:
            raise ValueError("heartbeat interval must be positive")
        self.heartbeat_interval = heartbeat_interval
        self.pipeline = SharedIngestionPipeline(sessions)

    async def run_next(self, worker_id: str) -> UUID | None:
        with self.sessions.begin() as session:
            run = IngestionRunRepository(session).claim_next(worker_id, self.now())
            if run is None:
                return None
            run_id = run.id
        run_started = time.perf_counter()
        metrics.gauge("fx_analyzer_worker_active_runs", 1)
        LOGGER.info("ingestion run started", extra={"event": "run_started", "run_id": str(run_id), "outcome": "running"})
        heartbeat = asyncio.create_task(self._heartbeat_until_cancelled(run_id))
        try:
            self._heartbeat(run_id)
            with self.sessions() as session:
                run = IngestionRunRepository(session).get(run_id)
                assert run is not None
                scope_ids = [item.id for item in IngestionScopeRepository(session).list_for_run(run_id)]
            for scope_id in scope_ids:
                await self._execute_scope(run_id, scope_id)
                self._heartbeat(run_id)
            with self.sessions.begin() as session:
                manager = RunManager(session, code_version=self.code_version)
                status = manager.derive_status(run_id)
                manager.runs.finalize(run_id, status, self.now())
            LOGGER.info("ingestion run completed", extra={
                "event": "run_completed", "run_id": str(run_id), "outcome": status,
                "duration_seconds": round(time.perf_counter() - run_started, 6),
            })
        finally:
            metrics.gauge("fx_analyzer_worker_active_runs", 0)
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        return run_id

    async def _heartbeat_until_cancelled(self, run_id: UUID) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            self._heartbeat(run_id)

    async def _execute_scope(self, run_id: UUID, scope_id: UUID) -> None:
        try:
            with self.sessions.begin() as session:
                runs, scopes = IngestionRunRepository(session), IngestionScopeRepository(session)
                run, scope = runs.get(run_id), scopes.get(scope_id)
                assert run is not None and scope is not None
                policy = ConflictPolicy.REJECT if run.trigger_type == "manual" else ConflictPolicy.SKIP
                claim = ScopeCoordinator(session).claim(
                    run_id=run.id, dataset_key=str(run.provider_dataset_id), scope_type=scope.scope_type,
                    series_id=scope.series_id, start=scope.start_date, end=scope.end_date, policy=policy,
                )
                if not claim.acquired:
                    scopes.complete(scope.id, "skipped_conflict", self.now(), _empty_counts(), error_code=claim.reason)
                    return
                scopes.start(scope.id, self.now())
            with self.sessions() as session:
                run, scope = IngestionRunRepository(session).get(run_id), IngestionScopeRepository(session).get(scope_id)
                assert run is not None and scope is not None
                binding = self.bindings(run, scope)
            provider = "bank_of_canada" if scope.scope_type == "fx" else "bis"
            dataset = binding.request.dataset
            started = time.perf_counter()
            result = await self.pipeline.execute(run=run, scope=scope, binding=binding)
            with self.sessions.begin() as session:
                IngestionScopeRepository(session).complete(
                    scope_id, "succeeded", self.now(), result.counters,
                    retry_count=result.retry_count, last_http_status=result.last_http_status,
                )
            duration = time.perf_counter() - started
            metrics.increment("fx_analyzer_ingestion_runs_total", provider=provider, dataset=dataset, status="succeeded")
            metrics.observe("fx_analyzer_ingestion_run_duration_seconds", duration, provider=provider, dataset=dataset)
            for outcome in ("inserted", "unchanged", "revised"):
                amount = result.counters[f"{outcome}_count"]
                if amount:
                    metrics.increment("fx_analyzer_observations_total", amount, provider=provider, outcome=outcome)
            LOGGER.info("ingestion scope completed", extra={
                "event": "scope_completed", "run_id": str(run_id), "scope_id": str(scope_id),
                "provider": provider, "dataset": dataset, "duration_seconds": round(duration, 6),
                "outcome": "succeeded", "error_context": {"counts": dict(result.counters)},
            })
        except Exception as exc:
            with self.sessions.begin() as session:
                scope = IngestionScopeRepository(session).get(scope_id)
                if scope is not None and scope.status in ("pending", "running"):
                    counters = _empty_counts()
                    counters["failed_count"] = 1
                    IngestionScopeRepository(session).complete(
                        scope_id, "failed", self.now(), counters,
                        error_code=type(exc).__name__[:100],
                        error_details={"message": str(exc)[:500]},
                    )
            LOGGER.error("ingestion scope failed", extra={
                "event": "scope_completed", "run_id": str(run_id), "scope_id": str(scope_id),
                "outcome": "failed", "error_context": {"error_type": type(exc).__name__},
            })

    def _heartbeat(self, run_id: UUID) -> None:
        with self.sessions.begin() as session:
            IngestionRunRepository(session).heartbeat(run_id, self.now())


def _empty_counts() -> dict[str, int]:
    return {name: 0 for name in COUNTERS}


def _reason(exc: Exception) -> str:
    context = getattr(exc, "context", {})
    return str(context.get("code") or type(exc).__name__).upper()[:100]


def _provider(binding: PipelineBinding) -> str:
    return "bank_of_canada" if "valet" in binding.request.dataset else "bis"
