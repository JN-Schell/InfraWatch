"""PostgreSQL / TimescaleDB-only checks (skipped on the default SQLite test database).

Run with INFRAWATCH_TEST_DATABASE_URL=postgresql://... . CI sets INFRAWATCH_TEST_EXPECT_TIMESCALE=1 on the TimescaleDB
service so that a missing extension FAILS the job instead of silently skipping.
"""
import os

import pytest
from sqlalchemy import text

PG_URL = os.environ.get("INFRAWATCH_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL.startswith("postgres"), reason="requires PostgreSQL (INFRAWATCH_TEST_DATABASE_URL)")
EXPECT_TIMESCALE = os.environ.get("INFRAWATCH_TEST_EXPECT_TIMESCALE") == "1"


def _has_timescale(conn) -> bool:
    return conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'")).scalar() is not None


def test_server_runs_on_postgresql(client, app):
    assert app.state.db.engine.dialect.name == "postgresql"
    assert client.get("/api/v1/health").json()["status"] == "ok"


def test_time_series_tables_are_hypertables(client, app):
    """`client` starts the app lifespan, which runs the migrations (incl. the hypertable conversion)."""
    with app.state.db.engine.connect() as conn:
        if not _has_timescale(conn):
            if EXPECT_TIMESCALE:
                pytest.fail("TimescaleDB extension expected (INFRAWATCH_TEST_EXPECT_TIMESCALE=1) but is not installed")
            pytest.skip("TimescaleDB extension not available on this PostgreSQL")
        hypertables = {r[0] for r in conn.execute(text("SELECT hypertable_name FROM timescaledb_information.hypertables"))}
    assert {"metrics", "service_checks"} <= hypertables


def test_hypertable_conversion_is_idempotent_across_restarts(client, app):
    """Starting the app again on an existing schema must not fail (migrations are a no-op at head)."""
    from infrawatch_server.db import Database

    Database(app.state.settings.database_url).migrate()


def test_timestamps_roundtrip_as_utc_on_postgres(client, admin, app):
    """timestamptz columns return aware UTC values (guards the UTCDateTime decorator against dialect differences)."""
    from datetime import datetime, timedelta, timezone

    from conftest import push, register_host, sample

    hid, key = register_host(client, admin)
    ts = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=1)
    assert push(client, key, sample(ts=ts, cpu=12.5)).json()["accepted"] == 1
    pts = client.get(f"/api/v1/hosts/{hid}/metrics/export?format=json&range=1h", headers=admin).json()
    assert len(pts) == 1 and datetime.fromisoformat(pts[0]["ts"]) == ts and pts[0]["cpu_percent"] == 12.5


def test_host_search_is_case_insensitive_on_postgres(client, admin):
    """ILIKE path in /hosts?search= (SQLite LIKE is already case-insensitive for ASCII, so this guards PG semantics)."""
    from conftest import register_host

    register_host(client, admin, hostname="Web-Prod-01")
    names = [h["hostname"] for h in client.get("/api/v1/hosts?search=web-PROD", headers=admin).json()]
    assert names == ["Web-Prod-01"]
