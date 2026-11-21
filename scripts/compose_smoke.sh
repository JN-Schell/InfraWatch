#!/usr/bin/env bash
# End-to-end smoke test of the documented Docker Compose deployment (issue #2).
# Brings the stack up exactly as the README describes, logs in, enrolls a real agent
# and asserts that the host becomes "online" over plain HTTP and again over the Caddy TLS profile.
# Requires: docker compose, python3 with `pip install ./agent`, curl.   Usage: scripts/compose_smoke.sh
set -euo pipefail
cd "$(dirname "$0")/.."

WORK=$(mktemp -d)
ADMIN_PW="smoke-$(python3 -c 'import secrets;print(secrets.token_hex(8))')"
cat > .env <<ENV
POSTGRES_PASSWORD=$(python3 -c 'import secrets;print(secrets.token_hex(16))')
INFRAWATCH_SECRET_KEY=$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')
INFRAWATCH_ADMIN_PASSWORD=$ADMIN_PW
INFRAWATCH_TRUST_PROXY_HEADERS=true
ENV
AGENT_PID=""
cleanup() {
  rc=$?
  [ -n "$AGENT_PID" ] && kill "$AGENT_PID" 2>/dev/null || true
  if [ $rc -ne 0 ]; then echo "--- compose ps"; docker compose --profile tls ps -a || true
    echo "--- logs"; docker compose --profile tls logs --no-color --tail=80 || true; fi
  docker compose --profile tls down -v >/dev/null 2>&1 || true
  rm -rf "$WORK" .env
  exit $rc
}
trap cleanup EXIT

json() { python3 -c "import sys,json;print(json.load(sys.stdin)$1)"; }
wait_for() {  # wait_for <description> <timeout-seconds> <command...>
  local what=$1 t=$2; shift 2
  for _ in $(seq "$t"); do "$@" >/dev/null 2>&1 && return 0; sleep 1; done
  echo "TIMEOUT waiting for: $what" >&2; return 1
}

# Runs one agent against $1 (server URL) with optional CA bundle $2; asserts the host reaches "online".
agent_roundtrip() {
  local url=$1 ca=${2:-} name=$3 base=$4 token
  local curl_ca=(); [ -n "$ca" ] && curl_ca=(--cacert "$ca")
  local jwt; jwt=$(curl -fsS "${curl_ca[@]}" "$base/api/v1/auth/login" -H 'content-type: application/json' \
    -d "{\"username\":\"admin\",\"password\":\"$ADMIN_PW\"}" | json "['access_token']")
  token=$(curl -fsS "${curl_ca[@]}" "$base/api/v1/enrollment-tokens" -H "authorization: Bearer $jwt" \
    -H 'content-type: application/json' -d "{\"label\":\"$name\",\"environment\":\"smoke\"}" | json "['token']")
  mkdir -p "$WORK/$name"
  {
    echo "server_url: $url"; echo "interval: 2"; echo "state_dir: $WORK/$name"
    [ -n "$ca" ] && echo "ca_bundle: $ca"
  } > "$WORK/$name.yaml"
  INFRAWATCH_ENROLLMENT_TOKEN=$token infrawatch-agent -c "$WORK/$name.yaml" run > "$WORK/$name.log" 2>&1 &
  AGENT_PID=$!
  online() {
    curl -fsS "${curl_ca[@]}" "$base/api/v1/hosts?environment=smoke" -H "authorization: Bearer $jwt" |
      python3 -c "import sys,json;h=json.load(sys.stdin);sys.exit(0 if h and h[0]['status']=='online' else 1)"
  }
  if ! wait_for "agent '$name' to report" 60 online; then cat "$WORK/$name.log" >&2; return 1; fi
  echo "OK: host registered via $base and reported online"
  kill "$AGENT_PID"; wait "$AGENT_PID" 2>/dev/null || true; AGENT_PID=""
}

echo "== docker compose up (README quick-start)"
docker compose up -d --build
healthy() { curl -fsS http://localhost:8000/api/v1/health; }
wait_for "server health" 90 healthy
# Hardening claims in docker-compose.yml must actually hold at runtime.
sid=$(docker compose ps -q server)
[ "$(docker inspect -f '{{.HostConfig.ReadonlyRootfs}}' "$sid")" = true ]
[ "$(docker exec "$sid" id -u)" != 0 ]
echo "OK: server healthy, read-only rootfs, non-root"

echo "== plain HTTP agent"
agent_roundtrip http://localhost:8000 "" plain http://localhost:8000

echo "== TLS profile (Caddy internal CA + ca_bundle)"
docker compose --profile tls up -d
tls_up() { docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt "$WORK/ca.pem" && curl -fsS --cacert "$WORK/ca.pem" https://localhost/api/v1/health; }
wait_for "caddy TLS" 60 tls_up
agent_roundtrip https://localhost "$WORK/ca.pem" tls https://localhost
echo "ALL SMOKE CHECKS PASSED"
