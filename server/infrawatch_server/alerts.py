"""Alert evaluation engine.

Lifecycle:   open -> acknowledged -> resolved   (auto-resolves when condition clears)
Storm control:
  * Duplicate suppression: one non-resolved alert per fingerprint (rule+host+subject).
    Re-triggers only bump `occurrences`/`last_triggered_at`; no new alert, no notification.
  * Cooldown: after an alert resolves, the same fingerprint cannot open a new alert until
    the rule's cooldown has elapsed (damps flapping).
  * Maintenance windows suppress new alerts for covered hosts.
  * Notification is sent once when an alert opens and once on resolution.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .config import Settings
from .notify import Notifier

log = logging.getLogger("infrawatch.alerts")


def host_status(host: models.Host, now: datetime, offline_after: int) -> str:
    if host.revoked:
        return "revoked"
    if host.last_seen is None:
        return "pending"  # registered but has never reported: NOT considered monitored
    return "online" if (now - host.last_seen).total_seconds() <= offline_after else "offline"


def _window_covers(w: models.MaintenanceWindow, host: models.Host) -> bool:
    if w.host_id == host.id:
        return True
    return w.host_id is None and (w.environment is None or w.environment == host.environment) and (
        w.group is None or w.group == host.group
    )


def in_maintenance(db: Session, host: models.Host, now: datetime) -> bool:
    q = select(models.MaintenanceWindow).where(
        models.MaintenanceWindow.starts_at <= now, models.MaintenanceWindow.ends_at >= now
    )
    return any(_window_covers(w, host) for w in db.scalars(q))


class _Cycle:
    """Data for one evaluation cycle, loaded in a constant number of queries (not per rule x host)."""

    def __init__(self, db: Session, rules: Sequence[models.AlertRule], hosts: Sequence[models.Host], now: datetime) -> None:
        self.now = now
        self.windows = list(db.scalars(select(models.MaintenanceWindow).where(
            models.MaintenanceWindow.starts_at <= now, models.MaintenanceWindow.ends_at >= now)))
        self.open_alerts: dict[str, models.Alert] = {}
        for a in db.scalars(select(models.Alert).where(models.Alert.status != "resolved")
                            .order_by(models.Alert.opened_at)):
            self.open_alerts[a.fingerprint] = a
        # Most recent resolution per fingerprint, only as far back as any cooldown can matter.
        self.last_resolved: dict[str, datetime] = {}
        max_cd = max((r.cooldown_seconds for r in rules), default=0)
        if max_cd > 0:
            for fp, at in db.execute(
                select(models.Alert.fingerprint, models.Alert.resolved_at)
                .where(models.Alert.status == "resolved", models.Alert.resolved_at >= now - timedelta(seconds=max_cd))
            ):
                if at is not None and (fp not in self.last_resolved or at > self.last_resolved[fp]):
                    self.last_resolved[fp] = at
        self.metrics: dict[int, list] = {}
        metric_rules = [r for r in rules if r.type in ("cpu_high", "mem_high", "disk_low")]
        if metric_rules and hosts:
            horizon = max(max(r.for_seconds, 0) for r in metric_rules) + max(_tol(h) for h in hosts)
            for ts, host_id, cpu, mem, disk in db.execute(
                select(models.Metric.ts, models.Metric.host_id, models.Metric.cpu_percent,
                       models.Metric.mem_percent, models.Metric.disk_percent)
                .where(models.Metric.ts >= now - timedelta(seconds=horizon))
                .order_by(models.Metric.ts.desc())
            ):
                self.metrics.setdefault(host_id, []).append((ts, cpu, mem, disk))
        self.checks: dict[int, dict[str, models.ServiceCheck]] = {}
        if any(r.type in ("service_down", "response_slow") for r in rules):
            for c in db.scalars(select(models.ServiceCheck)
                                .where(models.ServiceCheck.ts >= now - timedelta(seconds=600))
                                .order_by(models.ServiceCheck.ts.desc())):
                self.checks.setdefault(c.host_id, {}).setdefault(c.name, c)

    def in_maintenance(self, host: models.Host) -> bool:
        return any(_window_covers(w, host) for w in self.windows)


def _tol(host: models.Host) -> int:
    return 2 * max(host.collection_interval or 15, 1) + 5  # allow ~2 missed samples at the window edge


def _rule_applies(rule: models.AlertRule, host: models.Host) -> bool:
    return (
        (rule.host_id is None or rule.host_id == host.id)
        and (rule.environment is None or rule.environment == host.environment)
        and (rule.group is None or rule.group == host.group)
    )


_COLS = {"cpu": 1, "mem": 2, "disk": 3}


def _sustained(cyc: _Cycle, host: models.Host, for_seconds: int, col: str, predicate, invert: bool = False):
    """Return (violating, latest_value). Violating iff there is >=1 sample in the window and
    every sample in it satisfies predicate. A fresh sample must exist (not stale).
    `invert` evaluates 100 - value (free disk space from disk usage)."""
    now = cyc.now
    window = max(for_seconds, 0)
    tol = _tol(host)
    i = _COLS[col]
    cutoff = now - timedelta(seconds=window + tol)
    rows = [(r[0], None if r[i] is None else (100 - r[i] if invert else r[i]))
            for r in cyc.metrics.get(host.id, []) if r[0] >= cutoff]
    if not rows:
        return False, None
    latest_ts, latest_val = rows[0]
    if latest_val is None:
        return False, None
    if window:
        in_window = [(t, v) for t, v in rows if t >= now - timedelta(seconds=window)]
        # must have data covering (most of) the window, otherwise we haven't observed it long enough
        oldest_needed = now - timedelta(seconds=window)
        if rows[-1][0] > oldest_needed + timedelta(seconds=tol):
            return False, latest_val
        return bool(in_window) and all(v is not None and predicate(v) for _, v in in_window), latest_val
    return predicate(latest_val), latest_val


def _conditions(cyc: _Cycle, rule: models.AlertRule, host: models.Host, settings: Settings):
    """Yield (subject, violated, value, title, message)."""
    t = rule.type
    now = cyc.now
    if t not in ("host_down", "service_down") and rule.threshold is None:
        return  # misconfigured rule (the API validates this; the database does not): nothing to compare against
    thr: float = rule.threshold if rule.threshold is not None else 0.0
    if t in ("cpu_high", "mem_high"):
        col = "cpu" if t == "cpu_high" else "mem"
        label = "CPU" if t == "cpu_high" else "Memory"
        v, val = _sustained(cyc, host, rule.for_seconds, col, lambda x: x > thr)
        yield "", v, val, f"{label} high on {host.hostname}", (
            f"{label} utilization {val:.1f}% exceeds {thr:g}%" if val is not None else "")
    elif t == "disk_low":
        v, val = _sustained(cyc, host, rule.for_seconds, "disk", lambda x: x < thr, invert=True)
        yield "", v, val, f"Low disk space on {host.hostname}", (
            f"Free disk space {val:.1f}% is below {thr:g}%" if val is not None else "")
    elif t == "host_down":
        status = host_status(host, now, settings.offline_after_seconds)
        yield "", status == "offline", None, f"Host {host.hostname} is unavailable", (
            f"No data received since {host.last_seen.isoformat() if host.last_seen else 'never'}")
    elif t in ("service_down", "response_slow"):
        seen = cyc.checks.get(host.id, {})  # latest result per service on this host (recent window)
        for name, c in seen.items():
            if rule.service_name and rule.service_name != name:
                continue
            if t == "service_down":
                yield name, not c.ok, None, f"Service {name} down on {host.hostname}", (
                    f"{c.kind} check {c.target} failed: {c.error or 'unhealthy'}")
            else:
                slow = c.ok and c.response_ms is not None and c.response_ms > thr
                yield name, slow, c.response_ms, f"Slow response from {name} on {host.hostname}", (
                    f"Response time {c.response_ms:.0f} ms exceeds {thr:g} ms" if c.response_ms else "")


def evaluate(db: Session, settings: Settings, notifier: Notifier, now: datetime) -> dict:
    """Run all enabled rules once. Returns counters (handy for tests/metrics)."""
    stats = {"opened": 0, "suppressed": 0, "resolved": 0, "cooldown": 0, "maintenance": 0}
    hosts = db.scalars(select(models.Host).where(models.Host.revoked.is_(False))).all()
    rules = db.scalars(select(models.AlertRule).where(models.AlertRule.enabled.is_(True))).all()
    channels = db.scalars(select(models.NotificationChannel).where(models.NotificationChannel.enabled.is_(True))).all()
    cyc = _Cycle(db, rules, hosts, now)
    active_fps: set[str] = set()
    evaluated_fps: set[str] = set()

    def notify(event: str, alert: models.Alert) -> None:
        for ch in channels:
            notifier.send(ch, event, alert)

    for rule in rules:
        for host in hosts:
            if not _rule_applies(rule, host):
                continue
            # A host that has never reported has no data: nothing to evaluate.
            if host.last_seen is None:
                continue
            for subject, violated, value, title, message in _conditions(cyc, rule, host, settings):
                fp = f"{rule.id}:{host.id}:{subject}"
                evaluated_fps.add(fp)
                existing = cyc.open_alerts.get(fp)
                if violated:
                    active_fps.add(fp)
                    if existing:
                        existing.occurrences += 1
                        existing.last_triggered_at = now
                        existing.value = value
                        stats["suppressed"] += 1
                        continue
                    if cyc.in_maintenance(host):
                        stats["maintenance"] += 1
                        continue
                    last_at = cyc.last_resolved.get(fp)
                    if last_at and (now - last_at).total_seconds() < rule.cooldown_seconds:
                        stats["cooldown"] += 1
                        continue
                    alert = models.Alert(
                        rule_id=rule.id, host_id=host.id, fingerprint=fp, severity=rule.severity, title=title,
                        message=message, value=value, opened_at=now, last_triggered_at=now, host=host,
                    )
                    db.add(alert)
                    db.flush()
                    cyc.open_alerts[fp] = alert
                    stats["opened"] += 1
                    notify("alert.opened", alert)
                    alert.notified_at = now
                elif existing:
                    _resolve(existing, "system", now)
                    cyc.open_alerts.pop(fp, None)
                    cyc.last_resolved[fp] = now
                    stats["resolved"] += 1
                    notify("alert.resolved", existing)

    # Auto-resolve open alerts whose rule was disabled/deleted or whose subject vanished (e.g. service removed).
    rules_by_id = {r.id: r for r in rules}  # enabled rules only: anything else is stale by definition
    for alert in list(cyc.open_alerts.values()):
        if alert.fingerprint in evaluated_fps:
            continue
        alert_rule = rules_by_id.get(alert.rule_id) if alert.rule_id else None
        stale = alert_rule is None or alert.host.revoked
        if not stale and alert_rule is not None and alert_rule.type in ("service_down", "response_slow"):
            stale = True  # service no longer reporting within the window
        if stale:
            _resolve(alert, "system", now)
            stats["resolved"] += 1
    db.commit()
    return stats


def _resolve(alert: models.Alert, by: str, now: datetime) -> None:
    alert.status = "resolved"
    alert.resolved_by = by
    alert.resolved_at = now
