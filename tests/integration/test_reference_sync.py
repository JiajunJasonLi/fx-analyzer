from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.application.reference import ReferenceDataService
from app.config.reference import load_reference_configuration
from app.database.models import Currency, FxPair, FxSeries, InterestRateSeries
from app.repositories.reference import SqlAlchemyReferenceDataRepository


@pytest.fixture
def migrated_engine():
    database_url = os.environ["TEST_DATABASE_URL"]
    config = Config("alembic.ini")
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()
        command.downgrade(config, "base")
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not configured")
def test_repeated_reference_sync_is_idempotent(migrated_engine) -> None:
    engine = migrated_engine
    configuration = load_reference_configuration(Path("config/reference-data.yaml"))
    with engine.connect() as connection, connection.begin() as transaction:
        session = Session(bind=connection)
        first = ReferenceDataService(SqlAlchemyReferenceDataRepository(session)).sync(configuration)
        second = ReferenceDataService(SqlAlchemyReferenceDataRepository(session)).sync(configuration)

        assert first.inserted > 0
        assert (second.inserted, second.updated, second.disabled) == (0, 0, 0)
        assert session.scalar(select(func.count()).select_from(Currency)) == 10
        assert session.scalar(select(func.count()).select_from(FxPair)) == 9
        assert session.scalar(select(func.count()).select_from(FxSeries)) == 9
        assert session.scalar(select(func.count()).select_from(InterestRateSeries)) == 10
        session.close()
        transaction.rollback()
