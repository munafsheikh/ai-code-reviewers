#!/usr/bin/env bash
# Roll the test environment back to the last verified image (single attempt, audited).
set -euo pipefail
cd "$(dirname "$0")/../.."
PROJECT="${ACR_TEST_PROJECT:-acr-test}"
STATE="${ACR_STATE_DIR:-out/deploy}/state.json"
target=$(infrastructure/scripts/py.sh -c "import json;print(json.load(open('$STATE'))['last_verified'])") || { echo "no verified release recorded" >&2; exit 1; }
export ACR_HOST_PORT="${ACR_TEST_PORT:-18088}" ACR_IMAGE="$target" ACR_PROFILE=balanced
# The fake runtime is part of the test environment, not the candidate: build it when this
# host does not have it yet (only that service; the reviewer stays the candidate image).
podman image inspect "${ACR_FAKE_RUNTIME_IMAGE:-acr-fake-runtime:local}" >/dev/null 2>&1 \
  || podman compose -p "$PROJECT" --profile test build -q fake-runtime
echo "{\"ts\":\"$(date -u +%FT%TZ)\",\"component\":\"deploy\",\"action\":\"rollback_start\",\"image\":\"$target\"}"
podman compose -p "$PROJECT" --profile test up -d --no-build --wait --wait-timeout "${DEPLOY_TIMEOUT:-180}"
BASE_URL="http://127.0.0.1:$ACR_HOST_PORT" infrastructure/scripts/smoke.sh
echo "{\"ts\":\"$(date -u +%FT%TZ)\",\"component\":\"deploy\",\"action\":\"rollback_verified\",\"image\":\"$target\"}"
