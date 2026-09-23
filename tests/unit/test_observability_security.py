from __future__ import annotations

import json
import logging
from dataclasses import replace
from io import StringIO
from pathlib import Path

from fastapi.testclient import TestClient

from app.config.reference import ConfigurationError, load_reference_configuration
from app.main import create_app
from app.observability.logging import JsonFormatter
from app.observability.metrics import MetricsRegistry, metrics


ROOT = Path(__file__).parents[2]


def test_json_logging_is_structured_bounded_and_sanitized() -> None:
    output = StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("acceptance.sanitization")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.info(
        "request authorization=Bearer-secret https://sensitive.example/path",
        extra={
            "event": "scope_completed", "request_id": "request-1", "run_id": "run-1",
            "scope_id": "scope-1", "provider": "bis", "dataset": "daily",
            "duration_seconds": 0.25, "outcome": "failed",
            "error_context": {"password": "nope", "payload": "raw", "reason": "timeout"},
        },
    )
    document = json.loads(output.getvalue())
    assert document["event"] == "scope_completed"
    assert document["provider"] == "bis"
    assert document["duration_seconds"] == 0.25
    assert document["error_context"] == {"reason": "timeout"}
    assert "Bearer-secret" not in output.getvalue()
    assert "sensitive.example" not in output.getvalue()
    assert "raw" not in output.getvalue()


def test_metrics_registry_rejects_unbounded_labels_and_renders_prometheus() -> None:
    registry = MetricsRegistry()
    registry.increment(
        "fx_analyzer_ingestion_runs_total", provider="bis", dataset="daily", status="succeeded"
    )
    registry.observe("fx_analyzer_provider_request_duration_seconds", 0.125, provider="bis")
    rendered = registry.render()
    assert 'provider="bis"' in rendered
    assert "fx_analyzer_provider_request_duration_seconds_sum" in rendered
    assert 'fx_analyzer_provider_request_duration_seconds_bucket{le="0.5",provider="bis"} 1' in rendered
    try:
        registry.increment("fx_analyzer_ingestion_runs_total", run_id="unbounded")
    except ValueError:
        pass
    else:
        raise AssertionError("unbounded metric label accepted")


def test_metrics_endpoint_is_opt_in(monkeypatch: object) -> None:
    monkeypatch.delenv("METRICS_ENABLED", raising=False)
    disabled = TestClient(create_app()).get("/metrics")
    assert disabled.status_code == 404

    monkeypatch.setenv("METRICS_ENABLED", "true")
    metrics.clear()
    metrics.gauge("fx_analyzer_worker_active_runs", 0)
    enabled = TestClient(create_app()).get("/metrics")
    assert enabled.status_code == 200
    assert "fx_analyzer_worker_active_runs 0" in enabled.text


def test_security_defaults_and_dependency_pins_are_present() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    compose = (ROOT / "compose.yaml").read_text()
    project = (ROOT / "pyproject.toml").read_text()
    assert "USER app" in dockerfile
    assert compose.count("127.0.0.1:") >= 2
    assert "APP_DATABASE_URL" in compose
    assert "docker-entrypoint-initdb.d" in compose
    for dependency in ("fastapi==", "httpx==", "SQLAlchemy==", "psycopg[binary]==", "pytest=="):
        assert dependency in project


def test_license_and_retention_records_and_gate() -> None:
    config = load_reference_configuration(ROOT / "config/reference-data.yaml")
    assert len(config.provider_datasets) == 2
    for dataset in config.provider_datasets:
        assert dataset.approval_state == "approved"
        assert dataset.retention_permitted is True
        assert dataset.license_url and dataset.attribution_text and dataset.redistribution_policy
        config.assert_ingestion_allowed(dataset.key)

    pending = replace(config, provider_datasets=tuple(
        replace(item, approval_state="pending", retention_permitted=False)
        for item in config.provider_datasets
    ))
    for dataset in pending.provider_datasets:
        try:
            pending.assert_ingestion_allowed(dataset.key)
        except ConfigurationError as exc:
            assert "license is not approved" in str(exc)
        else:
            raise AssertionError("pending dataset was allowed to ingest")


def test_phase_one_surface_has_no_ui_alert_or_trading_routes() -> None:
    paths = {route.path for route in create_app().routes}
    assert not any(fragment in path for path in paths for fragment in ("trade", "parity", "alert", "dashboard"))
