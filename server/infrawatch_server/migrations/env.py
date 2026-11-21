"""Alembic environment. Driven programmatically by `infrawatch_server.db.Database.migrate()` (a live
connection is passed in `config.attributes["connection"]`) or by the `alembic` CLI via `INFRAWATCH_DATABASE_URL`."""
from __future__ import annotations

from alembic import context

from infrawatch_server import models  # noqa: F401  (registers tables on Base.metadata)
from infrawatch_server.db import Base, make_engine

target_metadata = Base.metadata


def run_migrations() -> None:
    connection = context.config.attributes.get("connection")
    if connection is None:  # CLI usage
        from infrawatch_server.config import get_settings

        engine = make_engine(get_settings().database_url)
        with engine.connect() as connection:
            _run(connection)
        engine.dispose()
    else:
        _run(connection)


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


run_migrations()
