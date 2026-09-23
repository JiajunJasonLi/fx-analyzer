from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class IngestionRunRequest(BaseModel):
    provider: str
    dataset: str
    trigger_type: str
    start_date: date
    end_date: date
    series: list[str] | None = None


class Pagination(BaseModel):
    page_size: int = Field(default=100, ge=1, le=500)
