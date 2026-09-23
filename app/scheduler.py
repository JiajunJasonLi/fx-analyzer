from __future__ import annotations

import os
import signal
import threading
from datetime import datetime, timezone

from app.application.scheduling import DatabaseCommandSink, SchedulerPlanner
from app.config.reference import load_reference_configuration
from app.config.settings import Settings
from app.database.session import create_database_engine, create_session_factory


def run_scheduler() -> None:
    settings = Settings.from_env()
    if not settings.scheduler_enabled:
        return
    config = load_reference_configuration(settings.reference_config_path)
    sessions = create_session_factory(create_database_engine(settings))
    planner = SchedulerPlanner(config)
    stopped = threading.Event()

    def stop(signum: int, frame: object) -> None:
        del signum, frame
        stopped.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    while not stopped.is_set():
        now = datetime.now(timezone.utc)
        with sessions.begin() as session:
            sink = DatabaseCommandSink(
                session, config, code_version=os.getenv("CODE_VERSION", "unknown")
            )
            for command in planner.due_commands(now):
                sink.submit(command)
        stopped.wait(settings.scheduler_poll_interval)


def main() -> None:
    run_scheduler()


if __name__ == "__main__":
    main()
