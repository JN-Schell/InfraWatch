from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

BASELINE_REVISION = "0001"  # schema as of v0.1, created by create_all() before migrations existed


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url or url in ("sqlite://", "sqlite:///"):
            kwargs["poolclass"] = StaticPool
        engine = create_engine(url, **kwargs)

        @event.listens_for(engine, "connect")
        def _fk(dbapi_conn, _):  # enforce FKs on SQLite
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return engine
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(url, pool_pre_ping=True)


class Database:
    def __init__(self, url: str):
        self.engine = make_engine(url)
        self.sessionmaker = sessionmaker(self.engine, expire_on_commit=False)

    def migrate(self) -> None:
        """Bring the schema to the latest Alembic revision.

        A database created by the pre-migration `create_all()` (tables but no `alembic_version`) is adopted by stamping it
        at the baseline revision, so existing deployments upgrade in place instead of failing on "table already exists".
        """
        from alembic import command
        from alembic.config import Config

        cfg = Config()
        cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
        tables = set(inspect(self.engine).get_table_names())
        with self.engine.begin() as conn:
            cfg.attributes["connection"] = conn
            if "alembic_version" not in tables and "hosts" in tables:
                command.stamp(cfg, BASELINE_REVISION)
            command.upgrade(cfg, "head")

    def session(self) -> Session:
        return self.sessionmaker()

