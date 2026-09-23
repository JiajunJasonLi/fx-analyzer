from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol


class RunExecutor(Protocol):
    async def run_next(self, worker_id: str) -> object | None: ...


class Recovery(Protocol):
    def __call__(self, *, heartbeat_before: datetime, now: datetime) -> tuple[object, ...]: ...


@dataclass(frozen=True)
class WorkerOptions:
    poll_interval: float = 5.0
    lease_timeout: timedelta = timedelta(minutes=5)

    def __post_init__(self) -> None:
        if not 0.1 <= self.poll_interval <= 300:
            raise ValueError("worker poll interval must be between 0.1 and 300 seconds")
        if self.lease_timeout <= timedelta(0):
            raise ValueError("worker lease timeout must be positive")


class Worker:
    """Bounded polling loop; durable claim/execution remains in the orchestrator."""

    def __init__(
        self,
        executor: RunExecutor,
        recovery: Recovery,
        *,
        worker_id: str,
        options: WorkerOptions = WorkerOptions(),
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.executor = executor
        self.recovery = recovery
        self.worker_id = worker_id
        self.options = options
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.stop_requested = asyncio.Event()

    def stop(self) -> None:
        self.stop_requested.set()

    async def run(self) -> None:
        current = self._utc_now()
        self.recovery(
            heartbeat_before=current - self.options.lease_timeout,
            now=current,
        )
        while not self.stop_requested.is_set():
            run_id = await self.executor.run_next(self.worker_id)
            if run_id is not None:
                continue
            try:
                await asyncio.wait_for(
                    self.stop_requested.wait(), timeout=self.options.poll_interval
                )
            except TimeoutError:
                pass

    def _utc_now(self) -> datetime:
        value = self.now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("worker clock must return a timezone-aware timestamp")
        return value.astimezone(timezone.utc)
