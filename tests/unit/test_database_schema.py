from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import AddConstraint, CreateIndex, CreateTable

from app.database.base import Base
from app.database import models


EXPECTED_TABLES = {
    "currency", "economy", "economy_currency", "fx_pair", "provider_dataset",
    "fx_series", "interest_rate_series", "ingestion_run", "ingestion_scope",
    "raw_response", "raw_record", "fx_observation", "policy_rate_observation",
    "fx_observation_version", "policy_rate_observation_version",
    "fx_observation_version_run", "policy_rate_observation_version_run",
    "quarantined_record", "quality_result",
}


def test_all_phase_one_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_postgresql_types_and_constraints_compile() -> None:
    dialect = postgresql.dialect()
    ddl = "\n".join(str(CreateTable(table).compile(dialect=dialect)) for table in Base.metadata.sorted_tables)
    assert "TIMESTAMP WITH TIME ZONE" in ddl
    assert "NUMERIC(24, 12)" in ddl
    assert "JSONB" in ddl
    assert "BYTEA" in ddl
    circular = next(c for c in models.FxObservation.__table__.constraints if c.name == "fk_fx_observation_current_version")
    assert "DEFERRABLE INITIALLY DEFERRED" in str(AddConstraint(circular).compile(dialect=dialect))


def test_natural_keys_and_checks_are_present() -> None:
    fx = models.FxObservation.__table__
    version = models.FxObservationVersion.__table__
    assert any(isinstance(c, UniqueConstraint) and {col.name for col in c.columns} == {"fx_series_id", "observation_date"} for c in fx.constraints)
    assert any(isinstance(c, CheckConstraint) and c.name == "ck_fx_version_value" for c in version.constraints)
    assert any(isinstance(c, ForeignKeyConstraint) and c.name == "fk_fx_observation_current_version" for c in fx.constraints)


def test_required_query_and_one_open_version_indexes_compile() -> None:
    dialect = postgresql.dialect()
    indexes = [index for table in Base.metadata.tables.values() for index in table.indexes]
    names = {index.name for index in indexes}
    assert {"uq_fx_version_open", "uq_policy_version_open", "ix_fx_version_as_of", "ix_policy_version_as_of", "ix_quality_instrument_evaluated"} <= names
    open_index = next(index for index in indexes if index.name == "uq_fx_version_open")
    sql = str(CreateIndex(open_index).compile(dialect=dialect))
    assert "UNIQUE INDEX" in sql and "WHERE valid_to IS NULL" in sql


def test_lineage_foreign_keys_are_not_polymorphic() -> None:
    fx_target = next(iter(models.FxObservationVersionRun.__table__.c.observation_version_id.foreign_keys)).target_fullname
    policy_target = next(iter(models.PolicyRateObservationVersionRun.__table__.c.observation_version_id.foreign_keys)).target_fullname
    assert fx_target == "fx_observation_version.id"
    assert policy_target == "policy_rate_observation_version.id"


def test_check_constraints_match_domain_enum_values() -> None:
    expected_fragments = {
        (models.ProviderDataset, "ck_provider_dataset_provider_code"): {"bank_of_canada", "bis"},
        (models.ProviderDataset, "ck_provider_dataset_dataset_code"): {"valet_daily_fx", "bis_policy_rates_daily"},
        (models.IngestionRun, "ck_ingestion_run_trigger"): {"scheduled", "manual", "backfill", "retry"},
        (models.IngestionRun, "ck_ingestion_run_status"): {"pending", "running", "succeeded", "partially_succeeded", "failed"},
        (models.IngestionScope, "ck_ingestion_scope_status"): {"pending", "running", "succeeded", "failed", "skipped_conflict"},
        (models.FxObservationVersion, "ck_fx_version_validation_state"): {"valid", "valid_with_warnings", "invalid"},
        (models.PolicyRateObservationVersion, "ck_policy_version_validation_state"): {"valid", "valid_with_warnings", "invalid"},
        (models.QualityResult, "ck_quality_state"): {"complete", "incomplete", "stale", "not_due", "unknown"},
    }
    for (model, constraint_name), values in expected_fragments.items():
        constraint = next(item for item in model.__table__.constraints if item.name == constraint_name)
        sql = str(constraint.sqltext)
        assert all(f"'{value}'" in sql for value in values)


def test_pending_run_lifecycle_does_not_require_completion() -> None:
    constraint = next(
        item
        for item in models.IngestionRun.__table__.constraints
        if item.name == "ck_ingestion_run_lifecycle"
    )
    sql = str(constraint.sqltext)
    assert "status = 'pending'" in sql
    assert "started_at IS NULL" in sql
    assert "finished_at IS NULL" in sql
