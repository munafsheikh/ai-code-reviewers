#!/usr/bin/env bash
# End-to-end: build the image, start the compose stack with the fake runtime,
# exercise the HTTP service and the one-shot CLI container, then tear down.
set -euo pipefail
cd "$(dirname "$0")/../.."
export ACR_HOST_PORT="${ACR_HOST_PORT:-18089}" COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-acr-e2e}"
cleanup() { docker compose --profile test down --volumes --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker compose --profile test up -d --build --wait --wait-timeout 180
BASE_URL="http://127.0.0.1:$ACR_HOST_PORT" infrastructure/scripts/smoke.sh

mkdir -p out/e2e
set +e
docker compose --profile test run --rm -T reviewer review --profile balanced --format json \
  < benchmarks/fixtures/secrets-config/diff.patch > out/e2e/review.json
code=$?
set -e
[ "$code" = 1 ] || { echo "expected exit 1 (block), got $code" >&2; exit 1; }
docker compose --profile test run --rm -T --entrypoint python reviewer -m orchestrator.schema_check /dev/stdin < out/e2e/review.json
# Read-only, non-root, no capabilities
uid=$(docker compose --profile test exec -T reviewer id -u)
[ "$uid" = 10001 ] || { echo "reviewer runs as uid $uid" >&2; exit 1; }
if docker compose --profile test exec -T reviewer sh -c 'touch /opt/acr/x' 2>/dev/null; then echo "rootfs writable" >&2; exit 1; fi
echo "e2e passed"
