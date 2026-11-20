# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

Initial development. Version `0.1.0` is the working version in the code but has **not yet been tagged or released** (tracked in #21).

### Added
- Central FastAPI server with REST API, PostgreSQL/TimescaleDB-ready schema and static dashboard hosting (#22).
- Idempotent, validated metric ingestion (#23).
- One-time enrollment tokens and per-host API keys; agents cannot impersonate other hosts (#24).
- Monitoring agent: system metrics, HTTP/TCP/process checks, durable buffer, retry/backoff, graceful shutdown (#25).
- Alert engine with severities, acknowledgement/resolution, suppression, cooldown, maintenance windows, webhook notifications (#26).
- RBAC, Argon2id, JWT, rate limiting, audit log (#27).
- React dashboard (#28) and simulated-data generator (#29).
- Docker/Compose packaging (#30), GitHub Actions CI (#31) and documentation (#32).
- Engineering workflow: `AGENTS.md`, `CONTRIBUTING.md`, issue forms, PR template, CODEOWNERS, root `SECURITY.md` (#33).

### Security
- Static/SPA handler validates the requested path (no NUL, backslash, absolute or `..` segments, symlink escape) before any filesystem access (#47).
- Generated first-run admin password is written once to a mode-0600 file and is no longer logged (#48).
- Replaced references to the vacated owner handle (`sch3lly-stack`) in CODEOWNERS, security links and roadmap with `JN-Schell` (#53).

### Changed
- CI now runs Ruff and mypy (`lint` job); existing findings fixed (#35). `ruff format` is intentionally not enforced yet.
- Agent `flush()` is a no-op before registration; alert rules with a NULL threshold are skipped instead of raising; agent authentication uses one explicit 401 path for unknown/bad/revoked keys (#35).
- PostgreSQL/TimescaleDB-only tests: hypertable creation is asserted (CI fails if the extension is missing), plus UTC timestamp round-trip, restart idempotency and case-insensitive host search (#1).
