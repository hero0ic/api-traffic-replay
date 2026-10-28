"""SQLAlchemy engine and session helpers."""

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from replay_api.config import get_settings


class Base(DeclarativeBase):
    pass


def _sqlite_enable_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def make_engine(url: str | None = None) -> Engine:
    database_url = url or get_settings().database_url
    connect_args: dict[str, object] = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_engine(database_url, future=True, connect_args=connect_args)
    if database_url.startswith("sqlite"):
        event.listen(engine, "connect", _sqlite_enable_foreign_keys)
    return engine


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def configure_database(url: str) -> Engine:
    """Point the process at a different database. Used by tests."""

    global engine, SessionLocal
    engine = make_engine(url)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return engine


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables(bind: Engine | None = None) -> None:
    # Imported here so model metadata is registered before create_all.
    from replay_api import models as _models  # noqa: F401

    Base.metadata.create_all(bind or engine)


def drop_tables(bind: Engine | None = None) -> None:
    from replay_api import models as _models  # noqa: F401

    Base.metadata.drop_all(bind or engine)
