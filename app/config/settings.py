from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta


DEFAULT_DATABASE_URL = "postgresql+psycopg://localhost/fx_analyzer"
DEFAULT_LOG_LEVEL = "INFO"
VALID_LOG_LEVELS = frozenset({"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"})


@dataclass(frozen=True)
class Settings:
    database_url: str
    log_level: str
    reference_config_path: str = "config/reference-data.yaml"
    worker_poll_interval: float = 5.0
    worker_lease_timeout: timedelta = timedelta(minutes=5)
    scheduler_poll_interval: float = 60.0
    scheduler_enabled: bool = True
    metrics_enabled: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        database_url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL).strip()
        if not database_url:
            raise ValueError("DATABASE_URL must not be empty")

        log_level = os.environ.get("LOG_LEVEL", DEFAULT_LOG_LEVEL).strip().upper()
        if log_level not in VALID_LOG_LEVELS:
            choices = ", ".join(sorted(VALID_LOG_LEVELS))
            raise ValueError(f"LOG_LEVEL must be one of: {choices}")

        reference_config_path = os.environ.get(
            "REFERENCE_CONFIG_PATH", "config/reference-data.yaml"
        ).strip()
        if not reference_config_path:
            raise ValueError("REFERENCE_CONFIG_PATH must not be empty")

        return cls(
            database_url=database_url,
            log_level=log_level,
            reference_config_path=reference_config_path,
            worker_poll_interval=_bounded_float("WORKER_POLL_INTERVAL", 5.0, 0.1, 300.0),
            worker_lease_timeout=timedelta(seconds=_bounded_float("WORKER_LEASE_TIMEOUT", 300.0, 1.0, 86400.0)),
            scheduler_poll_interval=_bounded_float("SCHEDULER_POLL_INTERVAL", 60.0, 1.0, 3600.0),
            scheduler_enabled=_boolean("SCHEDULER_ENABLED", True),
            metrics_enabled=_boolean("METRICS_ENABLED", False),
        )


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _boolean(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    if raw.lower() not in {"true", "false", "1", "0"}:
        raise ValueError(f"{name} must be true or false")
    return raw.lower() in {"true", "1"}
