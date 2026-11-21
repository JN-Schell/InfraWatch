"""Alembic migrations: fresh upgrade equals the models, up/down works, and pre-migration databases are adopted."""
import os
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

import infrawatch_server
from infrawatch_server import models  # noqa: F401
from infrawatch_server.db import BASELINE_REVISION, Base, Database

URL = os.environ.get("INFRAWATCH_TEST_DATABASE_URL")


@pytest.fixture
def db(tmp_path):
    d = Database(URL or f"sqlite:///{tmp_path / 'm.db'}")
    if URL:  # real server: start empty
        Base.metadata.drop_all(d.engine)
        with d.engine.begin() as c:
            c.execute(text("DROP TABLE IF EXISTS alembic_version"))
    yield d
    d.engine.dispose()


def _diff(db):
    with db.engine.connect() as conn:
        return compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)


def _version(db):
    with db.engine.connect() as c:
        return c.execute(text("SELECT version_num FROM alembic_version")).scalar()


def test_fresh_database_migrates_to_head_and_matches_models(db):
    db.migrate()
    assert _diff(db) == [], "migrations are out of sync with models.py: add a new revision (see docs/DATABASE.md)"
    assert _version(db) == "0001"


def test_migrate_is_idempotent(db):
    db.migrate()
    db.migrate()
    assert _version(db) == "0001"


def test_downgrade_to_base_removes_everything_and_upgrade_restores_it(db):
    from alembic import command
    from alembic.config import Config

    db.migrate()
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(infrawatch_server.__file__).parent / "migrations"))
    with db.engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "base")
    assert set(inspect(db.engine).get_table_names()) <= {"alembic_version"}
    db.migrate()
    assert _diff(db) == []


def test_database_created_by_legacy_create_all_is_adopted_not_recreated(db):
    """v0.1 deployments have tables but no alembic_version: they must be stamped, keep their data, and not error."""
    Base.metadata.create_all(db.engine)
    with db.engine.begin() as c:
        c.execute(text("INSERT INTO users (username, password_hash, role, disabled, created_at) "
                       "VALUES ('legacy', 'x', 'viewer', false, '2026-01-01T00:00:00+00:00')"))
    db.migrate()
    assert _version(db) == BASELINE_REVISION
    with db.engine.connect() as c:
        assert c.execute(text("SELECT username FROM users")).scalar() == "legacy"
    assert _diff(db) == []


def test_auto_migrate_can_be_disabled(tmp_path):
    from fastapi.testclient import TestClient

    from infrawatch_server.config import Settings
    from infrawatch_server.main import create_app

    s = Settings(database_url=f"sqlite:///{tmp_path / 'off.db'}", secret_key="k" * 40, admin_password="adminpassword1",
                 run_background_tasks=False, frontend_dir="/nonexistent", auto_migrate=False)
    app = create_app(s)
    with pytest.raises(Exception, match="no such table"):  # schema is the operator's job when auto_migrate=false
        with TestClient(app):
            pass
