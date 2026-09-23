from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_session
from app.api.serialization import observation, page
from app.application.queries.observations import ObservationQueryService
from app.application.queries.operations import ResourceNotFoundError


router = APIRouter(prefix="/api/v1/policy-rates", tags=["policy rates"])


@router.get("")
def history(start_date: date, end_date: date, series: str | None = None,
            economy: str | None = None, currency: str | None = None,
            as_of: datetime | None = None, cursor: str | None = None,
            page_size: int = Query(100, ge=1, le=500),
            session: Session = Depends(get_session)) -> dict[str, object]:
    return page(ObservationQueryService(session).policy_history(
        start=start_date, end=end_date, series=series, economy=economy, currency=currency,
        as_of=as_of, cursor=cursor, page_size=page_size,
    ))


@router.get("/latest")
def latest(series: str | None = None, economy: str | None = None,
           currency: str | None = None, as_of: datetime | None = None,
           session: Session = Depends(get_session)) -> dict[str, object]:
    result = ObservationQueryService(session).policy_latest(
        series=series, economy=economy, currency=currency, as_of=as_of,
    )
    if result is None:
        raise ResourceNotFoundError("policy-rate observation not found")
    return observation(result)
