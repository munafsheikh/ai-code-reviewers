#!/usr/bin/env bash
# Deploy IMAGE to a disposable, isolated test environment (own compose project,
# fake runtime, loopback port), smoke-test it, and roll back to the last verified
# release on failure. Idempotent: re-running with the same image converges.
#   deploy.sh IMAGE
set -euo pipefail
cd "$(dirname "$0")/../.."
IMAGE="${1:?usage: deploy.sh IMAGE}"
PROJECT="${ACR_TEST_PROJECT:-acr-test}"
export ACR_HOST_PORT="${ACR_TEST_PORT:-18088}" ACR_IMAGE="$IMAGE" ACR_PROFILE=balanced
STATE_DIR="${ACR_STATE_DIR:-out/deploy}"
STATE="$STATE_DIR/state.json"
mkdir -p "$STATE_DIR"
log() { echo "{\"ts\":\"$(date -u +%FT%TZ)\",\"component\":\"deploy\",\"project\":\"$PROJECT\",$1}"; }
compose() { docker compose -p "$PROJECT" --profile test "$@"; }

last_verified=$(python3 -c "import json;print(json.load(open('$STATE')).get('last_verified',''))" 2>/dev/null || true)
log "\"action\":\"deploy_start\",\"image\":\"$IMAGE\",\"last_verified\":\"$last_verified\""

if compose up -d --no-build --wait --wait-timeout "${DEPLOY_TIMEOUT:-180}" && BASE_URL="http://127.0.0.1:$ACR_HOST_PORT" infrastructure/scripts/smoke.sh; then
  digest=$(docker image inspect --format '{{.Id}}' "$IMAGE")
  python3 - "$STATE" "$IMAGE" "$digest" <<'PY'
import json, sys, datetime, os
path, image, digest = sys.argv[1:]
state = json.load(open(path)) if os.path.exists(path) else {"history": []}
state.update(last_verified=image, last_verified_id=digest, verified_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
state["history"] = (state.get("history", []) + [{"image": image, "id": digest, "result": "verified"}])[-20:]
json.dump(state, open(path, "w"), indent=2)
PY
  log "\"action\":\"deploy_verified\",\"image\":\"$IMAGE\""
  exit 0
fi

diag="$STATE_DIR/diagnostics-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$diag"
compose ps -a > "$diag/ps.txt" 2>&1 || true
compose logs --no-color --tail=500 > "$diag/logs.txt" 2>&1 || true
log "\"action\":\"deploy_failed\",\"image\":\"$IMAGE\",\"diagnostics\":\"$diag\""
if [ -n "$last_verified" ] && [ "$last_verified" != "$IMAGE" ]; then
  infrastructure/deployment/rollback.sh || log "\"action\":\"rollback_failed\""
else
  log "\"action\":\"no_rollback_target\""
fi
exit 1
