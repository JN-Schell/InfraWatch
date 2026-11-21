# Database and migrations

The schema is managed by [Alembic](https://alembic.sqlalchemy.org/). Migrations live in
`server/infrawatch_server/migrations/versions/` and ship inside the server package.

## How it runs
* On startup the server runs `alembic upgrade head` (`Database.migrate()`), unless `INFRAWATCH_AUTO_MIGRATE=false`.
  With auto-migrate off, you must migrate yourself before starting the server (CLI below).
* **Existing v0.1 databases** (created by the old `create_all()`, so they have tables but no `alembic_version`) are
  adopted automatically: they are stamped at the baseline revision `0001`, keep all data, and then upgraded normally.
* On PostgreSQL the baseline migration converts `metrics` and `service_checks` to TimescaleDB hypertables when the
  extension is available (best effort, each step in a savepoint; plain PostgreSQL and SQLite work without it).
* Run a single server instance at first start / upgrade; concurrent migrators are not coordinated.

## Workflow for a schema change
1. Edit `models.py`.
2. Generate a revision against a scratch database that is at the current head (run from `server/`):
   ```bash
   cd server && export INFRAWATCH_DATABASE_URL=sqlite:////tmp/scratch.db
   python -m alembic upgrade head
   python -m alembic revision --autogenerate -m "add widgets" --rev-id 0002
   ```
3. **Review and edit the generated file** (autogenerate cannot see renames, data migrations, or TimescaleDB specifics).
   Do not import application models in a migration; migrations are frozen snapshots. Write a working `downgrade()`.
4. `pytest server/tests/test_migrations.py`: it fails if `models.py` and the migrations disagree, and exercises
   upgrade, downgrade and legacy adoption. CI runs it on SQLite and on TimescaleDB/PostgreSQL.
5. Describe the migration and any risk (locks, backfills) in the PR.

## CLI
`alembic` (config in `server/alembic.ini`, run from `server/`) uses the packaged environment, which reads `INFRAWATCH_DATABASE_URL`:
```bash
cd server
python -m alembic upgrade head
python -m alembic current
```
