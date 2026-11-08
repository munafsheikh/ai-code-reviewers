#!/usr/bin/env bash
# Roll the test environment back to the last verified image (single attempt, audited).
set -euo pipefail
cd "$(dirname "$0")/../.."
PROJECT="${ACR_TEST_PROJECT:-acr-test}"
STATE="${ACR_STATE_DIR:-out/deploy}/state.json"
target=$(infrastructure/scripts/py.sh -c "import json;print(json.load(open('$STATE'))['last_verified'])") || { echo "no verified release recorded" >&2; exit 1; }
export ACR_HOST_PORT="${ACR_TEST_PORT:-18088}" ACR_IMAGE="$target" ACR_PROFILE=balanced
echo "{\"ts\":\"$(date -u +%FT%TZ)\",\"component\":\"deploy\",\"action\":\"rollback_start\",\"image\":\"$target\"}"
docker compose -p "$PROJECT" --profile test up -d --no-build --wait --wait-timeout "${DEPLOY_TIMEOUT:-180}"
BASE_URL="http://127.0.0.1:$ACR_HOST_PORT" infrastructure/scripts/smoke.sh
echo "{\"ts\":\"$(date -u +%FT%TZ)\",\"component\":\"deploy\",\"action\":\"rollback_verified\",\"image\":\"$target\"}"
