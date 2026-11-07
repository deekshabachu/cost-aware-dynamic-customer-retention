"""Database URL and SQLAlchemy engine/session configuration."""

import os

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import sessionmaker


DEFAULT_DATABASE_URL = "sqlite:///./data/customer_retention.db"


def create_database_engine(database_url: str | None = None) -> Engine:
    """Create an engine, enabling SQLite foreign keys on every connection."""

    url = database_url or os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    database_engine = create_engine(url, connect_args=connect_args)

    if url.startswith("sqlite"):

        @event.listens_for(database_engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return database_engine


# Creating an Engine does not create the SQLite file or any tables.
engine = create_database_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

