from __future__ import annotations

import os
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="TEST_DATABASE_URL is required for PostgreSQL schema integration tests",
)


@pytest.fixture
def migrated_engine():
    assert DATABASE_URL is not None
    assert DATABASE_URL.startswith("postgresql")
    config = Config("alembic.ini")
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = DATABASE_URL
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_engine(DATABASE_URL)
    try:
        yield engine
    finally:
        engine.dispose()
        command.downgrade(config, "base")
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def test_clean_upgrade_has_full_schema_and_query_indexes(migrated_engine) -> None:
    inspector = inspect(migrated_engine)
    assert "fx_observation_version" in inspector.get_table_names()
    assert "policy_rate_observation_version" in inspector.get_table_names()
    assert "raw_response" in inspector.get_table_names()
    index_names = {item["name"] for item in inspector.get_indexes("fx_observation_version")}
    assert {"uq_fx_version_open", "ix_fx_version_as_of"} <= index_names


def test_exact_decimal_utc_and_constraints(migrated_engine) -> None:
    # PostgreSQL itself must perform these semantics; SQLite is intentionally not used.
    with migrated_engine.connect() as connection:
        value = connection.scalar(text("SELECT CAST(:value AS NUMERIC(24, 12))"), {"value": Decimal("1.234567890123")})
        zone = connection.scalar(text("SHOW TIME ZONE"))
    assert value == Decimal("1.234567890123")
    assert zone == "UTC"

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as connection:
            connection.execute(
                text("INSERT INTO currency (id, code, name, is_active) VALUES (gen_random_uuid(), 'usd', 'US Dollar', true)")
            )


def test_restrictive_foreign_keys(migrated_engine) -> None:
    foreign_keys = inspect(migrated_engine).get_foreign_keys("fx_series")
    assert foreign_keys
    assert all(fk["options"].get("ondelete") == "RESTRICT" for fk in foreign_keys)
