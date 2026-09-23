from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.models import (
    FxObservationVersionRun,
    PolicyRateObservationVersionRun,
    RawRecord,
    RawResponse,
)


class RawDataRepository:
    """Persistence operations for immutable provider payloads and their lineage.

    This repository deliberately never commits. The ingestion application service
    owns the transaction, so raw storage and any later canonical writes can share
    one transaction while raw rows are always flushed first.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_response(self, **values: Any) -> RawResponse:
        response = RawResponse(**values)
        self._session.add(response)
        self._session.flush()
        return response

    def get_response(self, raw_response_id: UUID) -> RawResponse | None:
        return self._session.get(RawResponse, raw_response_id)

    def get_or_create_record(
        self,
        *,
        raw_response_id: UUID,
        record_path: str,
        provider_natural_key: str | None = None,
        record_checksum: str | None = None,
        source_metadata: dict[str, Any] | None = None,
    ) -> RawRecord:
        existing = self._session.scalar(
            select(RawRecord).where(
                RawRecord.raw_response_id == raw_response_id,
                RawRecord.record_path == record_path,
            )
        )
        if existing is not None:
            if (
                existing.provider_natural_key != provider_natural_key
                or existing.record_checksum != record_checksum
                or existing.source_metadata != (source_metadata or {})
            ):
                raise ValueError("raw record locator already exists with different metadata")
            return existing

        record = RawRecord(
            raw_response_id=raw_response_id,
            record_path=record_path,
            provider_natural_key=provider_natural_key,
            record_checksum=record_checksum,
            source_metadata=source_metadata or {},
        )
        try:
            with self._session.begin_nested():
                self._session.add(record)
                self._session.flush()
            return record
        except IntegrityError:
            # A concurrent parser may have inserted the same deterministic path.
            existing = self._session.scalar(
                select(RawRecord).where(
                    RawRecord.raw_response_id == raw_response_id,
                    RawRecord.record_path == record_path,
                )
            )
            if existing is None:
                raise
            if (
                existing.provider_natural_key != provider_natural_key
                or existing.record_checksum != record_checksum
                or existing.source_metadata != (source_metadata or {})
            ):
                raise ValueError("raw record locator already exists with different metadata")
            return existing

    def add_fx_lineage(
        self,
        *,
        observation_version_id: UUID,
        ingestion_run_id: UUID,
        raw_record_id: UUID,
        observed_at: datetime,
    ) -> FxObservationVersionRun:
        return self._add_lineage(
            FxObservationVersionRun,
            observation_version_id=observation_version_id,
            ingestion_run_id=ingestion_run_id,
            raw_record_id=raw_record_id,
            observed_at=observed_at,
        )

    def add_policy_rate_lineage(
        self,
        *,
        observation_version_id: UUID,
        ingestion_run_id: UUID,
        raw_record_id: UUID,
        observed_at: datetime,
    ) -> PolicyRateObservationVersionRun:
        return self._add_lineage(
            PolicyRateObservationVersionRun,
            observation_version_id=observation_version_id,
            ingestion_run_id=ingestion_run_id,
            raw_record_id=raw_record_id,
            observed_at=observed_at,
        )

    def _add_lineage(self, model: type[Any], **values: Any) -> Any:
        key = (
            values["observation_version_id"],
            values["ingestion_run_id"],
            values["raw_record_id"],
        )
        existing = self._session.get(model, key)
        if existing is not None:
            if existing.observed_at != values["observed_at"]:
                existing.observed_at = max(existing.observed_at, values["observed_at"])
                self._session.flush()
            return existing
        lineage = model(**values)
        self._session.add(lineage)
        self._session.flush()
        return lineage
