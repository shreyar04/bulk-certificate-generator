"""Database engine, session factory and the FastAPI session dependency."""

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app import config


class Base(DeclarativeBase):
    """Parent class of every ORM model."""


def make_engine(url: str) -> Engine:
    """Create an engine. Tests call this with a temporary database URL."""
    is_sqlite = url.startswith("sqlite")
    # FastAPI runs sync code in a thread pool, so SQLite must allow use from several threads.
    # This is safe here because every request / background task uses its OWN session.
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    engine = create_engine(url, connect_args=connect_args)

    if is_sqlite:
        # SQLite ignores foreign keys unless you switch them on for every connection.
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


engine = make_engine(config.DATABASE_URL)

# autoflush=False: we decide exactly when data is sent to the database (with commit()).
SessionLocal = sessionmaker(bind=engine, autoflush=False)


def get_db():
    """FastAPI dependency: give each request its own session and always close it.

    NOTE: SessionLocal is looked up when the function runs (not when the module is
    imported). That is what lets the tests swap in a temporary database.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
