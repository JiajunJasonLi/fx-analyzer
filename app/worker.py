from __future__ import annotations

import asyncio
import os
import signal
import socket
from datetime import datetime, timezone

from app.application.ingestion.orchestrator import IngestionOrchestrator
from app.application.ingestion.run_manager import RunManager
from app.application.runtime_bindings import RuntimeBindingFactory
from app.application.worker_runtime import Worker, WorkerOptions
from app.config.reference import load_reference_configuration
from app.config.settings import Settings
from app.database.session import create_database_engine, create_session_factory


async def run_worker() -> None:
    settings = Settings.from_env()
    config = load_reference_configuration(settings.reference_config_path)
    sessions = create_session_factory(create_database_engine(settings))
    orchestrator = IngestionOrchestrator(
        sessions,
        code_version=os.getenv("CODE_VERSION", "unknown"),
        bindings=RuntimeBindingFactory(sessions, config),
    )

    def recover(**values: datetime) -> tuple[object, ...]:
        with sessions.begin() as session:
            return RunManager(
                session, code_version=os.getenv("CODE_VERSION", "unknown")
            ).recover_expired(**values)

    worker = Worker(
        orchestrator,
        recover,
        worker_id=f"{socket.gethostname()}:{os.getpid()}",
        options=WorkerOptions(
            settings.worker_poll_interval, settings.worker_lease_timeout
        ),
        now=lambda: datetime.now(timezone.utc),
    )
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, worker.stop)
    await worker.run()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
