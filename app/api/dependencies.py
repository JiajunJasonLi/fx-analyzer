from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy.orm import Session, sessionmaker

from app.application.queries.operations import ServiceUnavailableError
from app.config.reference import ConfigurationError, ReferenceConfiguration, load_reference_configuration
from app.config.settings import Settings
from app.database.session import create_database_engine, create_session_factory


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()


@lru_cache
def get_reference_config() -> ReferenceConfiguration:
    try:
        return load_reference_configuration(get_settings().reference_config_path)
    except ConfigurationError as exc:
        raise ServiceUnavailableError("reference configuration is unavailable") from exc


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return create_session_factory(create_database_engine(get_settings()))


def get_session() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
