from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey,
    ForeignKeyConstraint, Index, Integer, LargeBinary, Numeric, SmallInteger,
    String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base

UUID_PK = UUID(as_uuid=True)
UTC_TS = DateTime(timezone=True)
JSON = JSONB


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID_PK, primary_key=True, default=uuid.uuid4)


class Currency(Base):
    __tablename__ = "currency"
    __table_args__ = (
        CheckConstraint("code = upper(code) AND char_length(code) = 3", name="ck_currency_code"),
        CheckConstraint("name <> ''", name="ck_currency_name"),
        CheckConstraint("minor_units IS NULL OR minor_units >= 0", name="ck_currency_minor_units"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(3), unique=True)
    name: Mapped[str] = mapped_column(Text)
    minor_units: Mapped[int | None] = mapped_column(SmallInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class Economy(Base):
    __tablename__ = "economy"
    __table_args__ = (
        CheckConstraint("code <> ''", name="ck_economy_code"),
        CheckConstraint("name <> ''", name="ck_economy_name"),
        CheckConstraint("time_zone <> ''", name="ck_economy_time_zone"),
        CheckConstraint("economy_type IN ('country','currency_union')", name="ck_economy_type"),
        CheckConstraint("iso_country_code IS NULL OR (iso_country_code = upper(iso_country_code) AND char_length(iso_country_code) = 2)", name="ck_economy_iso_code"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(Text, unique=True)
    iso_country_code: Mapped[str | None] = mapped_column(String(2))
    name: Mapped[str] = mapped_column(Text)
    time_zone: Mapped[str] = mapped_column(Text)
    economy_type: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class EconomyCurrency(Base):
    __tablename__ = "economy_currency"
    __table_args__ = (CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_economy_currency_dates"),)
    economy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("economy.id", ondelete="RESTRICT"), primary_key=True)
    currency_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("currency.id", ondelete="RESTRICT"), primary_key=True)
    effective_from: Mapped[date] = mapped_column(Date, primary_key=True)
    effective_to: Mapped[date | None] = mapped_column(Date)


class FxPair(Base):
    __tablename__ = "fx_pair"
    __table_args__ = (
        UniqueConstraint("base_currency_id", "quote_currency_id", name="uq_fx_pair_currencies"),
        CheckConstraint("base_currency_id <> quote_currency_id", name="ck_fx_pair_distinct_currencies"),
        CheckConstraint("symbol <> ''", name="ck_fx_pair_symbol"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    base_currency_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("currency.id", ondelete="RESTRICT"))
    quote_currency_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("currency.id", ondelete="RESTRICT"))
    symbol: Mapped[str] = mapped_column(Text, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class ProviderDataset(Base):
    __tablename__ = "provider_dataset"
    __table_args__ = (
        UniqueConstraint("provider_code", "dataset_code", name="uq_provider_dataset_codes"),
        CheckConstraint("provider_code IN ('bank_of_canada','bis')", name="ck_provider_dataset_provider_code"),
        CheckConstraint("dataset_code IN ('valet_daily_fx','bis_policy_rates_daily')", name="ck_provider_dataset_dataset_code"),
        CheckConstraint("display_name <> ''", name="ck_provider_dataset_display_name"),
        CheckConstraint("approval_state IN ('pending','approved','rejected')", name="ck_provider_dataset_approval"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    provider_code: Mapped[str] = mapped_column(Text)
    dataset_code: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    configuration_reference: Mapped[str] = mapped_column(Text)
    license_url: Mapped[str | None] = mapped_column(Text)
    license_notes: Mapped[str | None] = mapped_column(Text)
    attribution_text: Mapped[str | None] = mapped_column(Text)
    redistribution_restrictions: Mapped[str | None] = mapped_column(Text)
    approval_state: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class FxSeries(Base):
    __tablename__ = "fx_series"
    __table_args__ = (
        UniqueConstraint("provider_dataset_id", "provider_symbol", name="uq_fx_series_provider_symbol"),
        CheckConstraint("frequency = 'daily'", name="ck_fx_series_frequency"),
        CheckConstraint("quote_type = 'reference'", name="ck_fx_series_quote_type"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    provider_dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("provider_dataset.id", ondelete="RESTRICT"))
    provider_symbol: Mapped[str] = mapped_column(Text)
    fx_pair_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fx_pair.id", ondelete="RESTRICT"))
    frequency: Mapped[str] = mapped_column(Text)
    quote_type: Mapped[str] = mapped_column(Text)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, server_default=text("'{}'::jsonb"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class InterestRateSeries(Base):
    __tablename__ = "interest_rate_series"
    __table_args__ = (
        UniqueConstraint("provider_dataset_id", "dataflow_key", "series_key", name="uq_interest_rate_series_key"),
        CheckConstraint("frequency = 'daily'", name="ck_interest_rate_series_frequency"),
        CheckConstraint("unit = 'percent_per_year'", name="ck_interest_rate_series_unit"),
        CheckConstraint("rate_type = 'policy_rate'", name="ck_interest_rate_series_rate_type"),
        CheckConstraint("title <> ''", name="ck_interest_rate_series_title"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    provider_dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("provider_dataset.id", ondelete="RESTRICT"))
    economy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("economy.id", ondelete="RESTRICT"))
    currency_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("currency.id", ondelete="RESTRICT"))
    dataflow_key: Mapped[str] = mapped_column(Text)
    series_key: Mapped[str] = mapped_column(Text)
    frequency: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(Text)
    rate_type: Mapped[str] = mapped_column(Text)
    collection_indicator: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, server_default=text("'{}'::jsonb"))
    publication_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, server_default=text("'{}'::jsonb"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


COUNTERS = ("fetched_count", "inserted_count", "unchanged_count", "revised_count", "quarantined_count", "failed_count")


class IngestionRun(Base):
    __tablename__ = "ingestion_run"
    __table_args__ = (
        CheckConstraint("trigger_type IN ('scheduled','manual','backfill','retry')", name="ck_ingestion_run_trigger"),
        CheckConstraint("status IN ('pending','running','succeeded','partially_succeeded','failed')", name="ck_ingestion_run_status"),
        CheckConstraint("requested_end >= requested_start", name="ck_ingestion_run_dates"),
        CheckConstraint("fetched_count >= 0 AND inserted_count >= 0 AND unchanged_count >= 0 AND revised_count >= 0 AND quarantined_count >= 0 AND failed_count >= 0", name="ck_ingestion_run_counts"),
        CheckConstraint("(status = 'pending' AND started_at IS NULL AND finished_at IS NULL) OR (status = 'running' AND started_at IS NOT NULL AND finished_at IS NULL) OR (status IN ('succeeded','partially_succeeded','failed') AND started_at IS NOT NULL AND finished_at IS NOT NULL)", name="ck_ingestion_run_lifecycle"),
        Index("ix_ingestion_run_dataset_requested", "provider_dataset_id", "requested_at"),
        Index("ix_ingestion_run_status_heartbeat", "status", "heartbeat_at"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingestion_run.id", ondelete="RESTRICT")
    )
    trigger_type: Mapped[str] = mapped_column(Text)
    provider_dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("provider_dataset.id", ondelete="RESTRICT"))
    requested_start: Mapped[date] = mapped_column(Date)
    requested_end: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text)
    config_checksum: Mapped[str] = mapped_column(Text)
    code_version: Mapped[str] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(UTC_TS)
    started_at: Mapped[datetime | None] = mapped_column(UTC_TS)
    finished_at: Mapped[datetime | None] = mapped_column(UTC_TS)
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTC_TS)
    fetched_count: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    inserted_count: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    unchanged_count: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    revised_count: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    quarantined_count: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    failed_count: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    error_code: Mapped[str | None] = mapped_column(Text)
    error_summary: Mapped[str | None] = mapped_column(Text)


class IngestionScope(Base):
    __tablename__ = "ingestion_scope"
    __table_args__ = (
        UniqueConstraint("run_id", "scope_type", "series_id", "start_date", "end_date", "attempt_number", name="uq_ingestion_scope_attempt"),
        CheckConstraint("scope_type IN ('fx','policy_rate')", name="ck_ingestion_scope_type"),
        CheckConstraint("status IN ('pending','running','succeeded','failed','skipped_conflict')", name="ck_ingestion_scope_status"),
        CheckConstraint("end_date >= start_date", name="ck_ingestion_scope_dates"),
        CheckConstraint("attempt_number > 0 AND retry_count >= 0", name="ck_ingestion_scope_attempts"),
        CheckConstraint("fetched_count >= 0 AND inserted_count >= 0 AND unchanged_count >= 0 AND revised_count >= 0 AND quarantined_count >= 0 AND failed_count >= 0", name="ck_ingestion_scope_counts"),
        Index("ix_ingestion_scope_series_dates", "scope_type", "series_id", "start_date", "end_date"),
        Index("ix_ingestion_scope_run_status", "run_id", "status"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingestion_run.id", ondelete="RESTRICT"))
    scope_type: Mapped[str] = mapped_column(Text)
    series_id: Mapped[uuid.UUID] = mapped_column(UUID_PK)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(UTC_TS)
    finished_at: Mapped[datetime | None] = mapped_column(UTC_TS)
    fetched_count: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    inserted_count: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    unchanged_count: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    revised_count: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    quarantined_count: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    failed_count: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    last_http_status: Mapped[int | None] = mapped_column(Integer)
    retry_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    error_code: Mapped[str | None] = mapped_column(Text)
    error_details: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class RawResponse(Base):
    __tablename__ = "raw_response"
    __table_args__ = (
        CheckConstraint("request_method = 'GET'", name="ck_raw_response_method"),
        CheckConstraint("response_status BETWEEN 100 AND 599", name="ck_raw_response_status"),
        CheckConstraint("body_size >= 0 AND body_size <= 52428800", name="ck_raw_response_body_size"),
        CheckConstraint("char_length(payload_checksum) = 64", name="ck_raw_response_checksum"),
        Index("ix_raw_response_run", "run_id"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingestion_run.id", ondelete="RESTRICT"))
    scope_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingestion_scope.id", ondelete="RESTRICT"))
    provider_dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("provider_dataset.id", ondelete="RESTRICT"))
    request_method: Mapped[str] = mapped_column(Text)
    endpoint_name: Mapped[str] = mapped_column(Text)
    request_parameters: Mapped[dict[str, Any]] = mapped_column(JSON)
    response_status: Mapped[int] = mapped_column(Integer)
    media_type: Mapped[str] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(UTC_TS)
    payload_checksum: Mapped[str] = mapped_column(String(64))
    body: Mapped[bytes] = mapped_column(LargeBinary)
    body_size: Mapped[int] = mapped_column(BigInteger)
    content_encoding: Mapped[str | None] = mapped_column(Text)
    response_metadata: Mapped[dict[str, Any]] = mapped_column(JSON)


class RawRecord(Base):
    __tablename__ = "raw_record"
    __table_args__ = (
        UniqueConstraint("raw_response_id", "record_path", name="uq_raw_record_path"),
        CheckConstraint("record_checksum IS NULL OR char_length(record_checksum) = 64", name="ck_raw_record_checksum"),
        Index("ix_raw_record_natural_key", "provider_natural_key"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    raw_response_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw_response.id", ondelete="RESTRICT"))
    record_path: Mapped[str] = mapped_column(Text)
    provider_natural_key: Mapped[str | None] = mapped_column(Text)
    record_checksum: Mapped[str | None] = mapped_column(String(64))
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON)


class FxObservation(Base):
    __tablename__ = "fx_observation"
    __table_args__ = (UniqueConstraint("fx_series_id", "observation_date", name="uq_fx_observation_natural"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    fx_series_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fx_series.id", ondelete="RESTRICT"))
    observation_date: Mapped[date] = mapped_column(Date)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID_PK, nullable=True)


class PolicyRateObservation(Base):
    __tablename__ = "policy_rate_observation"
    __table_args__ = (UniqueConstraint("interest_rate_series_id", "observation_date", name="uq_policy_rate_observation_natural"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    interest_rate_series_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("interest_rate_series.id", ondelete="RESTRICT"))
    observation_date: Mapped[date] = mapped_column(Date)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID_PK, nullable=True)


class FxObservationVersion(Base):
    __tablename__ = "fx_observation_version"
    __table_args__ = (
        UniqueConstraint("observation_id", "version_number", name="uq_fx_version_number"),
        UniqueConstraint("observation_id", "id", name="uq_fx_version_observation_id"),
        UniqueConstraint("observation_id", "version_fingerprint", "valid_from", name="uq_fx_version_fingerprint_from"),
        CheckConstraint("version_number > 0", name="ck_fx_version_number"),
        CheckConstraint("value > 0", name="ck_fx_version_value"),
        CheckConstraint("quote_type = 'reference'", name="ck_fx_version_quote_type"),
        CheckConstraint("char_length(version_fingerprint) = 64", name="ck_fx_version_fingerprint"),
        CheckConstraint("last_observed_at >= first_observed_at", name="ck_fx_version_observed_interval"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_fx_version_valid_interval"),
        CheckConstraint("validation_state IN ('valid','valid_with_warnings','invalid')", name="ck_fx_version_validation_state"),
        Index("uq_fx_version_open", "observation_id", unique=True, postgresql_where=text("valid_to IS NULL")),
        Index("ix_fx_version_as_of", "observation_id", "valid_from", "valid_to"),
        Index("ix_fx_version_first_observed", "first_observed_at"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    observation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fx_observation.id", ondelete="RESTRICT"))
    version_number: Mapped[int] = mapped_column(Integer)
    value: Mapped[Decimal] = mapped_column(Numeric(24, 12))
    quote_type: Mapped[str] = mapped_column(Text)
    version_fingerprint: Mapped[str] = mapped_column(String(64))
    provider_publication_timestamp: Mapped[datetime | None] = mapped_column(UTC_TS)
    first_observed_at: Mapped[datetime] = mapped_column(UTC_TS)
    last_observed_at: Mapped[datetime] = mapped_column(UTC_TS)
    valid_from: Mapped[datetime] = mapped_column(UTC_TS)
    valid_to: Mapped[datetime | None] = mapped_column(UTC_TS)
    validation_state: Mapped[str] = mapped_column(Text)
    validation_flags: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    provider_attributes: Mapped[dict[str, Any]] = mapped_column(JSON)
    originating_raw_record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw_record.id", ondelete="RESTRICT"))
    originating_ingestion_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingestion_run.id", ondelete="RESTRICT"))


class PolicyRateObservationVersion(Base):
    __tablename__ = "policy_rate_observation_version"
    __table_args__ = (
        UniqueConstraint("observation_id", "version_number", name="uq_policy_version_number"),
        UniqueConstraint("observation_id", "id", name="uq_policy_version_observation_id"),
        UniqueConstraint("observation_id", "version_fingerprint", "valid_from", name="uq_policy_version_fingerprint_from"),
        CheckConstraint("version_number > 0", name="ck_policy_version_number"),
        CheckConstraint("unit = 'percent_per_year'", name="ck_policy_version_unit"),
        CheckConstraint("frequency = 'daily'", name="ck_policy_version_frequency"),
        CheckConstraint("rate_type = 'policy_rate'", name="ck_policy_version_rate_type"),
        CheckConstraint("char_length(version_fingerprint) = 64", name="ck_policy_version_fingerprint"),
        CheckConstraint("last_observed_at >= first_observed_at", name="ck_policy_version_observed_interval"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_policy_version_valid_interval"),
        CheckConstraint("validation_state IN ('valid','valid_with_warnings','invalid')", name="ck_policy_version_validation_state"),
        Index("uq_policy_version_open", "observation_id", unique=True, postgresql_where=text("valid_to IS NULL")),
        Index("ix_policy_version_as_of", "observation_id", "valid_from", "valid_to"),
        Index("ix_policy_version_first_observed", "first_observed_at"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    observation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("policy_rate_observation.id", ondelete="RESTRICT"))
    version_number: Mapped[int] = mapped_column(Integer)
    value: Mapped[Decimal] = mapped_column(Numeric(24, 12))
    unit: Mapped[str] = mapped_column(Text)
    frequency: Mapped[str] = mapped_column(Text)
    rate_type: Mapped[str] = mapped_column(Text)
    collection_indicator: Mapped[str] = mapped_column(Text)
    dataset_version: Mapped[str | None] = mapped_column(Text)
    version_fingerprint: Mapped[str] = mapped_column(String(64))
    provider_publication_timestamp: Mapped[datetime | None] = mapped_column(UTC_TS)
    first_observed_at: Mapped[datetime] = mapped_column(UTC_TS)
    last_observed_at: Mapped[datetime] = mapped_column(UTC_TS)
    valid_from: Mapped[datetime] = mapped_column(UTC_TS)
    valid_to: Mapped[datetime | None] = mapped_column(UTC_TS)
    validation_state: Mapped[str] = mapped_column(Text)
    validation_flags: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    provider_attributes: Mapped[dict[str, Any]] = mapped_column(JSON)
    originating_raw_record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw_record.id", ondelete="RESTRICT"))
    originating_ingestion_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingestion_run.id", ondelete="RESTRICT"))


class FxObservationVersionRun(Base):
    __tablename__ = "fx_observation_version_run"
    observation_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fx_observation_version.id", ondelete="RESTRICT"), primary_key=True)
    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingestion_run.id", ondelete="RESTRICT"), primary_key=True)
    raw_record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw_record.id", ondelete="RESTRICT"), primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(UTC_TS)


class PolicyRateObservationVersionRun(Base):
    __tablename__ = "policy_rate_observation_version_run"
    observation_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("policy_rate_observation_version.id", ondelete="RESTRICT"), primary_key=True)
    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingestion_run.id", ondelete="RESTRICT"), primary_key=True)
    raw_record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw_record.id", ondelete="RESTRICT"), primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(UTC_TS)


class QuarantinedRecord(Base):
    __tablename__ = "quarantined_record"
    __table_args__ = (
        CheckConstraint("stage IN ('parse','map','normalize','validate','conflict')", name="ck_quarantine_stage"),
        CheckConstraint("resolution_state IN ('unresolved','resolved','ignored')", name="ck_quarantine_resolution"),
        Index("ix_quarantine_run_state", "run_id", "resolution_state"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingestion_run.id", ondelete="RESTRICT"))
    scope_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingestion_scope.id", ondelete="RESTRICT"))
    raw_record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("raw_record.id", ondelete="RESTRICT"))
    provider_natural_key: Mapped[str | None] = mapped_column(Text)
    reason_code: Mapped[str] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTC_TS)
    updated_at: Mapped[datetime] = mapped_column(UTC_TS)
    resolution_state: Mapped[str] = mapped_column(Text)


class QualityResult(Base):
    __tablename__ = "quality_result"
    __table_args__ = (
        CheckConstraint("instrument_type IN ('fx_pair','policy_rate_series')", name="ck_quality_instrument_type"),
        CheckConstraint("quality_state IN ('complete','incomplete','stale','not_due','unknown')", name="ck_quality_state"),
        CheckConstraint("severity IN ('info','warning','error')", name="ck_quality_severity"),
        CheckConstraint("affected_end >= affected_start", name="ck_quality_dates"),
        Index("ix_quality_instrument_evaluated", "instrument_type", "instrument_id", "evaluated_at"),
        Index("ix_quality_run", "run_id"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingestion_run.id", ondelete="RESTRICT"))
    instrument_type: Mapped[str] = mapped_column(Text)
    instrument_id: Mapped[uuid.UUID] = mapped_column(UUID_PK)
    rule_code: Mapped[str] = mapped_column(Text)
    quality_state: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text)
    affected_start: Mapped[date] = mapped_column(Date)
    affected_end: Mapped[date] = mapped_column(Date)
    evaluated_at: Mapped[datetime] = mapped_column(UTC_TS)
    details: Mapped[dict[str, Any]] = mapped_column(JSON)


# Added after both sides are declared. DEFERRABLE resolves insertion ordering, while
# the composite key guarantees that the current version belongs to the observation.
FxObservation.__table__.append_constraint(
    ForeignKeyConstraint(
        [FxObservation.__table__.c.id, FxObservation.__table__.c.current_version_id],
        [FxObservationVersion.__table__.c.observation_id, FxObservationVersion.__table__.c.id],
        name="fk_fx_observation_current_version", deferrable=True, initially="DEFERRED", use_alter=True,
    )
)
PolicyRateObservation.__table__.append_constraint(
    ForeignKeyConstraint(
        [PolicyRateObservation.__table__.c.id, PolicyRateObservation.__table__.c.current_version_id],
        [PolicyRateObservationVersion.__table__.c.observation_id, PolicyRateObservationVersion.__table__.c.id],
        name="fk_policy_observation_current_version", deferrable=True, initially="DEFERRED", use_alter=True,
    )
)
