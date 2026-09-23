from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.application.scheduling import DatabaseCommandSink, SchedulerPlanner
from app.application.ingestion.orchestrator import IngestionOrchestrator
from app.application.worker_runtime import Worker, WorkerOptions
from app.config.reference import load_reference_configuration


CONFIG = Path(__file__).parents[2] / "config" / "reference-data.yaml"


def configuration():
    config = load_reference_configuration(CONFIG)
    return replace(config, provider_datasets=tuple(
        replace(item, approval_state="approved", retention_permitted=True)
        for item in config.provider_datasets
    ))


def test_bank_of_canada_is_due_only_after_publication_and_grace() -> None:
    planner = SchedulerPlanner(configuration())
    before = planner.due_commands(datetime(2026, 9, 21, 21, 29, tzinfo=timezone.utc))
    after = planner.due_commands(datetime(2026, 9, 21, 21, 30, tzinfo=timezone.utc))
    prior = next(item for item in before if item.command.provider.value == "bank_of_canada")
    assert prior.command.date_range.end.isoformat() == "2026-09-18"
    boc = next(item for item in after if item.command.provider.value == "bank_of_canada")
    assert boc.command.date_range.start.isoformat() == "2026-09-21"
    assert boc.command.date_range.end == boc.command.date_range.start


def test_scheduler_does_not_enqueue_unapproved_datasets() -> None:
    config = load_reference_configuration(CONFIG)
    pending = replace(config, provider_datasets=tuple(
        replace(item, approval_state="pending", retention_permitted=False)
        for item in config.provider_datasets
    ))
    planner = SchedulerPlanner(pending)
    assert planner.due_commands(datetime(2026, 9, 21, 22, 0, tzinfo=timezone.utc)) == ()


def test_bank_of_canada_skips_weekends_and_configured_holidays() -> None:
    planner = SchedulerPlanner(configuration())
    commands = planner.due_commands(datetime(2026, 9, 8, 1, 0, tzinfo=timezone.utc))
    boc = next(item for item in commands if item.command.provider.value == "bank_of_canada")
    # Monday September 7 is a configured Canadian holiday; Friday is latest due.
    assert boc.command.date_range.end.isoformat() == "2026-09-04"


def test_bis_uses_weekly_release_window_despite_daily_frequency() -> None:
    planner = SchedulerPlanner(configuration())
    before = planner.due_commands(datetime(2026, 9, 18, 9, 59, tzinfo=timezone.utc))
    after = planner.due_commands(datetime(2026, 9, 18, 10, 0, tzinfo=timezone.utc))
    before_bis = next(item for item in before if item.command.provider.value == "bis")
    after_bis = next(item for item in after if item.command.provider.value == "bis")
    assert before_bis.command.date_range.end.isoformat() == "2026-09-10"
    assert after_bis.command.date_range.end.isoformat() == "2026-09-17"
    assert (after_bis.command.date_range.end - after_bis.command.date_range.start).days == 6


class _Executor:
    def __init__(self) -> None:
        self.calls = 0

    async def run_next(self, worker_id: str) -> object | None:
        assert worker_id == "test-worker"
        self.calls += 1
        return None


def test_worker_recovers_expired_lease_then_stops_gracefully() -> None:
    executor = _Executor()
    recovered: list[tuple[datetime, datetime]] = []
    now = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)

    def recover(*, heartbeat_before: datetime, now: datetime) -> tuple[object, ...]:
        recovered.append((heartbeat_before, now))
        return (SimpleNamespace(id="expired"),)

    async def scenario() -> None:
        worker = Worker(executor, recover, worker_id="test-worker",
            options=WorkerOptions(0.1, timedelta(seconds=30)), now=lambda: now)
        task = asyncio.create_task(worker.run())
        while executor.calls == 0:
            await asyncio.sleep(0)
        worker.stop()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(scenario())
    assert recovered == [(now - timedelta(seconds=30), now)]
    assert executor.calls == 1


def test_worker_option_bounds_prevent_busy_or_unbounded_polling() -> None:
    for interval in (0.01, 301):
        try:
            WorkerOptions(poll_interval=interval)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid polling interval was accepted")


def test_database_sink_suppresses_already_covered_run() -> None:
    class Session:
        def __init__(self) -> None:
            self.results = iter((SimpleNamespace(id=uuid4()), uuid4()))

        def scalar(self, statement: object) -> object:
            del statement
            return next(self.results)

    config = configuration()
    scheduled = next(item for item in SchedulerPlanner(config).due_commands(
        datetime(2026, 9, 21, 22, 0, tzinfo=timezone.utc)
    ) if item.command.provider.value == "bank_of_canada")
    assert DatabaseCommandSink(Session(), config, code_version="test").submit(scheduled) is False  # type: ignore[arg-type]


def test_orchestrator_heartbeats_during_long_provider_work() -> None:
    async def scenario() -> int:
        orchestrator = object.__new__(IngestionOrchestrator)
        orchestrator.heartbeat_interval = 0.01
        beats: list[object] = []
        orchestrator._heartbeat = beats.append
        task = asyncio.create_task(orchestrator._heartbeat_until_cancelled("run-id"))  # type: ignore[arg-type]
        await asyncio.sleep(0.035)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return len(beats)

    assert asyncio.run(scenario()) >= 2
