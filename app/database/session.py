from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import Settings


def create_database_engine(settings: Settings, **kwargs: object) -> Engine:
    engine = create_engine(settings.database_url, pool_pre_ping=True, **kwargs)

    if engine.dialect.name == "postgresql":

        @event.listens_for(engine, "connect")
        def set_utc_timezone(dbapi_connection: object, connection_record: object) -> None:
            del connection_record
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            try:
                cursor.execute("SET TIME ZONE 'UTC'")
            finally:
                cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
