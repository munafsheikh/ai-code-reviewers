#!/usr/bin/env bash
# Post-deployment smoke test for a running reviewer service.
set -euo pipefail
cd "$(dirname "$0")/../.."
BASE_URL="${BASE_URL:-http://127.0.0.1:${ACR_HOST_PORT:-8088}}"
fail() { echo "{\"level\":\"error\",\"component\":\"smoke\",\"msg\":\"$1\"}" >&2; exit 1; }
curl_() { curl --noproxy '*' -sS --max-time "${SMOKE_TIMEOUT:-120}" "$@"; }

for i in $(seq 1 30); do curl_ -f "$BASE_URL/healthz" >/dev/null 2>&1 && break; [ "$i" = 30 ] && fail "healthz not ok"; sleep 2; done
ready=$(curl_ -f "$BASE_URL/readyz") || fail "readyz failed"
echo "readyz: $ready"
if [ "${REQUIRE_MODEL:-0}" = "1" ] && ! grep -q '"status": "ready"' <<<"$ready"; then fail "model runtime not ready"; fi

check() {  # fixture expected_gate
  local body gate
  body=$(curl_ -f -H 'Content-Type: text/plain' --data-binary "@benchmarks/fixtures/$1/diff.patch" "$BASE_URL/v1/review") \
    || fail "review request failed for $1"
  gate=$(python3 -c 'import json,sys; r=json.load(sys.stdin); print(r["gate"]["status"], r["run"]["degraded"])' <<<"$body")
  echo "fixture $1 -> $gate"
  [ "${gate%% *}" = "$2" ] || fail "fixture $1: expected gate $2, got $gate"
  if [ "${REQUIRE_MODEL:-0}" = "1" ] && [ "${gate##* }" = "True" ]; then fail "fixture $1 ran degraded"; fi
}
check java-leak-injection block
# A real model may legitimately add findings to the clean case; only assert it when rules decide alone.
[ "${REQUIRE_MODEL:-0}" = "1" ] || check python-clean pass
curl_ -f "$BASE_URL/metrics" | grep -q '^acr_reviews_total' || fail "metrics missing"
echo '{"level":"info","component":"smoke","msg":"smoke passed"}'
