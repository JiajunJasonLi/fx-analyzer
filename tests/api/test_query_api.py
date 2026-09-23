from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.dependencies import get_reference_config, get_session
from app.application.ingestion.scope_coordinator import ScopeConflictError
from app.application.queries.observations import (
    AmbiguousQueryError,
    ObservationPage,
    ObservationView,
    QueryValidationError,
    decode_cursor,
    encode_cursor,
    validate_history_range,
)
from app.application.queries.operations import ServiceUnavailableError
from app.main import create_app


NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def _view(day: date = date(2026, 9, 1), value: str = "1.347500000000") -> ObservationView:
    return ObservationView(
        uuid4(), uuid4(), 2, "fx_pair", "USDCAD", day, Decimal(value), "CAD_per_USD",
        "reference", None, "bank_of_canada", "FXUSDCAD", None, NOW, NOW, None, True,
        "valid_with_warnings", [{"code": "STALE", "severity": "warning"}], uuid4(), uuid4(),
    )


class _Queries:
    def __init__(self, session: object) -> None:
        del session

    def fx_history(self, **kwargs: object) -> ObservationPage:
        assert kwargs["pair"] == "USD/CAD"
        return ObservationPage((_view(),), "next")

    def fx_latest(self, **kwargs: object) -> ObservationView | None:
        if kwargs["pair"] == "explode":
            raise RuntimeError("database_url=secret")
        return _view() if kwargs["pair"] != "missing" else None

    def policy_history(self, **kwargs: object) -> ObservationPage:
        if not any(kwargs[key] for key in ("series", "economy", "currency")):
            raise QueryValidationError("IDENTIFYING_FILTER_REQUIRED", "provide a filter")
        return ObservationPage((), None)

    def policy_latest(self, **kwargs: object) -> ObservationView | None:
        if kwargs["currency"] == "EUR" and kwargs["series"] is None:
            raise AmbiguousQueryError("AMBIGUOUS_POLICY_RATE", "filters match multiple series")
        return None


def _client(monkeypatch: object) -> TestClient:
    from app.api.routers import fx, policy_rates

    monkeypatch.setattr(fx, "ObservationQueryService", _Queries)
    monkeypatch.setattr(policy_rates, "ObservationQueryService", _Queries)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: object()
    app.dependency_overrides[get_reference_config] = lambda: object()
    return TestClient(app, raise_server_exceptions=False)


def test_fx_history_serializes_precision_provenance_and_utc(monkeypatch: object) -> None:
    response = _client(monkeypatch).get(
        "/api/v1/fx-observations",
        params={"pair": "USD/CAD", "start_date": "2026-09-01", "end_date": "2026-09-02"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["value"] == "1.347500000000"
    assert body["items"][0]["retrieved_at"].endswith("Z")
    assert body["items"][0]["version_number"] == 2
    assert body["items"][0]["provenance"]["run_id"]
    assert body["items"][0]["validation"]["flags"][0]["code"] == "STALE"
    assert body["next_cursor"] == "next"


def test_missing_latest_uses_consistent_404(monkeypatch: object) -> None:
    response = _client(monkeypatch).get("/api/v1/fx-observations/latest", params={"pair": "missing"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert response.json()["error"]["request_id"]


def test_policy_filter_is_required(monkeypatch: object) -> None:
    response = _client(monkeypatch).get(
        "/api/v1/policy-rates", params={"start_date": "2026-01-01", "end_date": "2026-01-02"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IDENTIFYING_FILTER_REQUIRED"


def test_ambiguous_policy_latest_is_rejected(monkeypatch: object) -> None:
    response = _client(monkeypatch).get("/api/v1/policy-rates/latest", params={"currency": "EUR"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "AMBIGUOUS_POLICY_RATE"


def test_invalid_framework_input_uses_error_contract(monkeypatch: object) -> None:
    response = _client(monkeypatch).get("/api/v1/fx-observations/latest")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"


def test_cursor_round_trip_and_invalid_cursor() -> None:
    item_id = uuid4()
    assert decode_cursor(encode_cursor(date(2026, 9, 1), item_id)) == (date(2026, 9, 1), item_id)
    try:
        decode_cursor("not-a-cursor")
    except QueryValidationError as exc:
        assert exc.code == "INVALID_CURSOR"
    else:
        raise AssertionError("invalid cursor accepted")


def test_unbounded_and_reversed_ranges_are_rejected() -> None:
    for start, end, code in (
        (date(2026, 2, 1), date(2026, 1, 1), "INVALID_DATE_RANGE"),
        (date(2000, 1, 1), date(2026, 1, 1), "DATE_RANGE_TOO_LARGE"),
    ):
        try:
            validate_history_range(start, end)
        except QueryValidationError as exc:
            assert exc.code == code
        else:
            raise AssertionError("invalid range accepted")


def test_twenty_year_history_is_supported_but_range_remains_bounded() -> None:
    validate_history_range(date(2006, 9, 20), date(2026, 9, 20))
    try:
        validate_history_range(date(1900, 1, 1), date(2026, 9, 20))
    except QueryValidationError as exc:
        assert exc.code == "DATE_RANGE_TOO_LARGE"
    else:
        raise AssertionError("unbounded range accepted")


def test_as_of_queries_enforce_knowledge_interval_and_no_future_dates() -> None:
    from app.application.queries.observations import ObservationQueryService

    instant = datetime(2026, 9, 2, 12, tzinfo=timezone.utc)
    fx_sql = str(ObservationQueryService._fx_query(instant))
    policy_sql = str(ObservationQueryService._policy_query(instant))
    for sql in (fx_sql, policy_sql):
        assert "valid_from <=" in sql
        assert "valid_to IS NULL" in sql
        assert "valid_to >" in sql
        assert "observation_date <=" in sql


def test_enqueue_returns_202_without_executing_work(monkeypatch: object) -> None:
    from app.api.routers import operations

    run = SimpleNamespace(
        id=uuid4(), parent_run_id=None, trigger_type="manual", requested_start=date(2026, 9, 1),
        requested_end=date(2026, 9, 2), status="pending", requested_at=NOW, started_at=None,
        finished_at=None, heartbeat_at=None, fetched_count=0, inserted_count=0, unchanged_count=0,
        revised_count=0, quarantined_count=0, failed_count=0, error_code=None, error_summary=None,
    )
    fake = SimpleNamespace(enqueue=lambda **kwargs: run)
    monkeypatch.setattr(operations, "_service", lambda session, config: fake)
    response = _client(monkeypatch).post("/api/v1/ingestion-runs", json={
        "provider": "bank_of_canada", "dataset": "valet_daily_fx", "trigger_type": "manual",
        "start_date": "2026-09-01", "end_date": "2026-09-02",
    })
    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert response.headers["location"].endswith(str(run.id))


def test_overlap_maps_to_409(monkeypatch: object) -> None:
    from app.api.routers import operations

    def conflict(**kwargs: object) -> object:
        raise ScopeConflictError("overlap")

    monkeypatch.setattr(operations, "_service", lambda session, config: SimpleNamespace(enqueue=conflict))
    response = _client(monkeypatch).post("/api/v1/ingestion-runs", json={
        "provider": "bank_of_canada", "dataset": "valet_daily_fx", "trigger_type": "manual",
        "start_date": "2026-09-01", "end_date": "2026-09-02",
    })
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OVERLAPPING_INGESTION_SCOPE"


def test_unavailable_configuration_maps_to_503(monkeypatch: object) -> None:
    from app.api.routers import operations

    def unavailable(**kwargs: object) -> object:
        raise ServiceUnavailableError("license approval unavailable")

    monkeypatch.setattr(operations, "_service", lambda session, config: SimpleNamespace(enqueue=unavailable))
    response = _client(monkeypatch).post("/api/v1/ingestion-runs", json={
        "provider": "bis", "dataset": "bis_policy_rates_daily", "trigger_type": "backfill",
        "start_date": "2026-09-01", "end_date": "2026-09-02",
    })
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_unexpected_error_maps_to_sanitized_500(monkeypatch: object) -> None:
    response = _client(monkeypatch).get("/api/v1/fx-observations/latest", params={"pair": "explode"})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret" not in response.text


def test_operations_query_endpoints_are_exposed(monkeypatch: object) -> None:
    from app.api.routers import operations

    fake = SimpleNamespace(
        run_detail=lambda run_id: (_ for _ in ()).throw(AssertionError("not used")),
        list_runs=lambda **kwargs: ((), None),
        quality=lambda **kwargs: (),
        quarantine_counts=lambda **kwargs: [{"reason_code": "BAD", "stage": "parse", "resolution_state": "unresolved", "count": 2}],
    )
    monkeypatch.setattr(operations, "_service", lambda session, config: fake)
    client = _client(monkeypatch)
    runs = client.get("/api/v1/ingestion-runs")
    quality = client.get("/api/v1/data-quality")
    quarantine = client.get("/api/v1/quarantine/counts")
    assert runs.status_code == 200 and runs.json() == {"items": [], "next_cursor": None}
    assert quality.status_code == 200 and quality.json() == {"items": []}
    assert quarantine.status_code == 200 and quarantine.json()["items"][0]["count"] == 2


def test_readiness_returns_503_with_component_status(monkeypatch: object) -> None:
    import app.main as main

    monkeypatch.setattr(main, "readiness", lambda session, config: {
        "status": "not_ready", "checks": {"database": True, "migrations": False, "configuration": True, "references": True}
    })
    app = create_app()
    app.dependency_overrides[get_session] = lambda: object()
    app.dependency_overrides[get_reference_config] = lambda: object()
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["migrations"] is False
