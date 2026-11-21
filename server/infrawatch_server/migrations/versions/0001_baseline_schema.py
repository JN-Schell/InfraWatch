"""baseline schema

Revision ID: 0001
Revises:
Create Date: 2026-11-20

Frozen snapshot of the schema as created by `Base.metadata.create_all` before migrations existed (v0.1).
Deployments created that way are adopted by `Database.migrate()`, which stamps them at this revision.
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def _enable_timescale() -> None:
    """Best effort: convert the time-series tables to hypertables when TimescaleDB is available (PostgreSQL only).
    Each attempt runs in a SAVEPOINT so a plain-PostgreSQL server (no extension) doesn't abort the migration."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    log = logging.getLogger("infrawatch.migrations")
    try:
        with bind.begin_nested():
            bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
    except Exception as exc:
        log.info("TimescaleDB not available, using plain PostgreSQL tables (%s)", type(exc).__name__)
        return
    for table in ("metrics", "service_checks"):
        try:
            with bind.begin_nested():
                bind.execute(sa.text(f"SELECT create_hypertable('{table}', 'ts', if_not_exists => TRUE, migrate_data => TRUE)"))
        except Exception as exc:
            log.warning("could not create hypertable %s: %s", table, exc)


def upgrade() -> None:
    op.create_table('audit_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('actor', sa.String(length=64), nullable=False),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('target', sa.String(length=255), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=False),
    sa.Column('detail', sa.JSON(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_log_ts'), 'audit_log', ['ts'], unique=False)
    op.create_table('enrollment_tokens',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('label', sa.String(length=128), nullable=False),
    sa.Column('environment', sa.String(length=64), nullable=False),
    sa.Column('group', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('used_by_host_id', sa.Integer(), nullable=True),
    sa.Column('created_by', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_table('hosts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('hostname', sa.String(length=255), nullable=False),
    sa.Column('os', sa.String(length=64), nullable=False),
    sa.Column('os_version', sa.String(length=255), nullable=False),
    sa.Column('arch', sa.String(length=32), nullable=False),
    sa.Column('agent_version', sa.String(length=32), nullable=False),
    sa.Column('environment', sa.String(length=64), nullable=False),
    sa.Column('group', sa.String(length=64), nullable=False),
    sa.Column('api_key_hash', sa.String(length=64), nullable=False),
    sa.Column('revoked', sa.Boolean(), nullable=False),
    sa.Column('is_simulated', sa.Boolean(), nullable=False),
    sa.Column('registered_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen', sa.DateTime(timezone=True), nullable=True),
    sa.Column('collection_interval', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_hosts_environment'), 'hosts', ['environment'], unique=False)
    op.create_index(op.f('ix_hosts_group'), 'hosts', ['group'], unique=False)
    op.create_index(op.f('ix_hosts_is_simulated'), 'hosts', ['is_simulated'], unique=False)
    op.create_table('notification_channels',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('url', sa.String(length=1024), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('min_severity', sa.String(length=16), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('disabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('username')
    )
    op.create_table('alert_rules',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('type', sa.String(length=32), nullable=False),
    sa.Column('threshold', sa.Float(), nullable=True),
    sa.Column('for_seconds', sa.Integer(), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('cooldown_seconds', sa.Integer(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('host_id', sa.Integer(), nullable=True),
    sa.Column('environment', sa.String(length=64), nullable=True),
    sa.Column('group', sa.String(length=64), nullable=True),
    sa.Column('service_name', sa.String(length=128), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['host_id'], ['hosts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('maintenance_windows',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('host_id', sa.Integer(), nullable=True),
    sa.Column('environment', sa.String(length=64), nullable=True),
    sa.Column('group', sa.String(length=64), nullable=True),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['host_id'], ['hosts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('metrics',
    sa.Column('host_id', sa.Integer(), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('cpu_percent', sa.Float(), nullable=True),
    sa.Column('mem_percent', sa.Float(), nullable=True),
    sa.Column('mem_available_bytes', sa.BigInteger(), nullable=True),
    sa.Column('mem_total_bytes', sa.BigInteger(), nullable=True),
    sa.Column('disk_percent', sa.Float(), nullable=True),
    sa.Column('disk_free_bytes', sa.BigInteger(), nullable=True),
    sa.Column('disk_total_bytes', sa.BigInteger(), nullable=True),
    sa.Column('net_sent_bps', sa.Float(), nullable=True),
    sa.Column('net_recv_bps', sa.Float(), nullable=True),
    sa.Column('uptime_seconds', sa.BigInteger(), nullable=True),
    sa.Column('load1', sa.Float(), nullable=True),
    sa.Column('load5', sa.Float(), nullable=True),
    sa.Column('load15', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['host_id'], ['hosts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('host_id', 'ts')
    )
    op.create_index('ix_metrics_ts', 'metrics', ['ts'], unique=False)
    op.create_table('service_checks',
    sa.Column('host_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('target', sa.String(length=512), nullable=False),
    sa.Column('ok', sa.Boolean(), nullable=False),
    sa.Column('response_ms', sa.Float(), nullable=True),
    sa.Column('status_code', sa.Integer(), nullable=True),
    sa.Column('error', sa.String(length=255), nullable=False),
    sa.ForeignKeyConstraint(['host_id'], ['hosts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('host_id', 'name', 'ts')
    )
    op.create_index('ix_checks_ts', 'service_checks', ['ts'], unique=False)
    op.create_table('alerts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('rule_id', sa.Integer(), nullable=True),
    sa.Column('host_id', sa.Integer(), nullable=False),
    sa.Column('fingerprint', sa.String(length=255), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('value', sa.Float(), nullable=True),
    sa.Column('opened_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_triggered_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('occurrences', sa.Integer(), nullable=False),
    sa.Column('acknowledged_by', sa.String(length=64), nullable=True),
    sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolved_by', sa.String(length=64), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('notified_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['host_id'], ['hosts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['rule_id'], ['alert_rules.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_alerts_fingerprint'), 'alerts', ['fingerprint'], unique=False)
    op.create_index(op.f('ix_alerts_host_id'), 'alerts', ['host_id'], unique=False)
    op.create_index(op.f('ix_alerts_status'), 'alerts', ['status'], unique=False)
    _enable_timescale()


def downgrade() -> None:
    op.drop_index(op.f('ix_alerts_status'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_host_id'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_fingerprint'), table_name='alerts')
    op.drop_table('alerts')
    op.drop_index('ix_checks_ts', table_name='service_checks')
    op.drop_table('service_checks')
    op.drop_index('ix_metrics_ts', table_name='metrics')
    op.drop_table('metrics')
    op.drop_table('maintenance_windows')
    op.drop_table('alert_rules')
    op.drop_table('users')
    op.drop_table('notification_channels')
    op.drop_index(op.f('ix_hosts_is_simulated'), table_name='hosts')
    op.drop_index(op.f('ix_hosts_group'), table_name='hosts')
    op.drop_index(op.f('ix_hosts_environment'), table_name='hosts')
    op.drop_table('hosts')
    op.drop_table('enrollment_tokens')
    op.drop_index(op.f('ix_audit_log_ts'), table_name='audit_log')
    op.drop_table('audit_log')
