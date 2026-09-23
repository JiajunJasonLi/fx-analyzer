from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_reference_config, get_session
from app.api.schemas import IngestionRunRequest
from app.api.serialization import json_value, utc_iso
from app.application.queries.operations import OperationsService
from app.config.reference import ReferenceConfiguration


router = APIRouter(prefix="/api/v1", tags=["operations"])


def _service(session: Session, config: ReferenceConfiguration) -> OperationsService:
    return OperationsService(session, config)


@router.post("/ingestion-runs", status_code=status.HTTP_202_ACCEPTED)
def enqueue(payload: IngestionRunRequest, response: Response,
            session: Session = Depends(get_session),
            config: ReferenceConfiguration = Depends(get_reference_config)) -> dict[str, Any]:
    run = _service(session, config).enqueue(
        provider=payload.provider, dataset=payload.dataset, trigger_type=payload.trigger_type,
        start=payload.start_date, end=payload.end_date,
        series=tuple(payload.series) if payload.series else None,
    )
    response.headers["Location"] = f"/api/v1/ingestion-runs/{run.id}"
    return _run(run)


@router.get("/ingestion-runs/{run_id}")
def run_detail(run_id: UUID, session: Session = Depends(get_session),
               config: ReferenceConfiguration = Depends(get_reference_config)) -> dict[str, Any]:
    detail = _service(session, config).run_detail(run_id)
    return {**_run(detail["run"]), "scopes": [_scope(item) for item in detail["scopes"]]}


@router.get("/ingestion-runs")
def runs(status_filter: str | None = Query(None, alias="status"), provider: str | None = None,
         start_date: date | None = None, end_date: date | None = None, cursor: str | None = None,
         page_size: int = Query(100, ge=1, le=200), session: Session = Depends(get_session),
         config: ReferenceConfiguration = Depends(get_reference_config)) -> dict[str, Any]:
    rows, next_cursor = _service(session, config).list_runs(
        status=status_filter, provider=provider, start=start_date, end=end_date,
        cursor=cursor, page_size=page_size,
    )
    return {"items": [{**_run(row), "provider": provider_code, "dataset": dataset_code}
                       for row, provider_code, dataset_code in rows], "next_cursor": next_cursor}


@router.get("/data-quality")
def quality(instrument_type: str | None = None, instrument_id: UUID | None = None,
            start_date: date | None = None, end_date: date | None = None,
            session: Session = Depends(get_session),
            config: ReferenceConfiguration = Depends(get_reference_config)) -> dict[str, Any]:
    rows = _service(session, config).quality(
        instrument_type=instrument_type, instrument_id=instrument_id, start=start_date, end=end_date,
    )
    return {"items": [{column.name: json_value(getattr(row, column.name)) for column in row.__table__.columns}
                       for row in rows]}


@router.get("/quarantine/counts")
def quarantine_counts(run_id: UUID | None = None, reason: str | None = None,
                      stage: str | None = None, session: Session = Depends(get_session),
                      config: ReferenceConfiguration = Depends(get_reference_config)) -> dict[str, Any]:
    return {"items": _service(session, config).quarantine_counts(run_id=run_id, reason=reason, stage=stage)}


def _run(run: Any) -> dict[str, Any]:
    return {
        "id": str(run.id), "parent_run_id": str(run.parent_run_id) if run.parent_run_id else None,
        "trigger_type": run.trigger_type, "requested_start": run.requested_start.isoformat(),
        "requested_end": run.requested_end.isoformat(), "status": run.status,
        "requested_at": utc_iso(run.requested_at), "started_at": utc_iso(run.started_at),
        "finished_at": utc_iso(run.finished_at), "heartbeat_at": utc_iso(run.heartbeat_at),
        "counts": {name: getattr(run, name) for name in ("fetched_count", "inserted_count", "unchanged_count", "revised_count", "quarantined_count", "failed_count")},
        "error": {"code": run.error_code, "summary": run.error_summary} if run.error_code else None,
    }


def _scope(scope: Any) -> dict[str, Any]:
    return {
        "id": str(scope.id), "type": scope.scope_type, "series_id": str(scope.series_id),
        "start_date": scope.start_date.isoformat(), "end_date": scope.end_date.isoformat(),
        "attempt_number": scope.attempt_number, "status": scope.status,
        "started_at": utc_iso(scope.started_at), "finished_at": utc_iso(scope.finished_at),
        "error_code": scope.error_code,
    }
