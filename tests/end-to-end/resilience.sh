#!/usr/bin/env bash
# Resilience: watchdog bounded restart + circuit open, and deploy auto-rollback.
set -euo pipefail
cd "$(dirname "$0")/../.."
IMAGE=acr-reviewer:resilience
ACR_IMAGE="$IMAGE" podman compose build --quiet reviewer
export ACR_TEST_PROJECT=acr-resilience ACR_TEST_PORT=18091 ACR_STATE_DIR=out/resilience
trap 'infrastructure/deployment/teardown.sh >/dev/null 2>&1 || true' EXIT
infrastructure/deployment/deploy.sh "$IMAGE"

export COMPOSE_PROJECT=acr-resilience MAX_RESTARTS=1 WATCHDOG_STATE=out/resilience/watchdog
c=$(podman ps -q --filter label=com.docker.compose.project=acr-resilience --filter label=com.docker.compose.service=reviewer)
podman stop "$c" >/dev/null && infrastructure/monitoring/watchdog.sh
podman stop "$c" >/dev/null
if infrastructure/monitoring/watchdog.sh; then echo "circuit did not open" >&2; exit 1; fi
podman start "$c" >/dev/null

printf 'FROM %s\nENTRYPOINT ["python","-c","import time; time.sleep(600)"]\n' "$IMAGE" | podman build -q -t acr-reviewer:resilience-broken - >/dev/null
if DEPLOY_TIMEOUT=45 infrastructure/deployment/deploy.sh acr-reviewer:resilience-broken; then echo "broken deploy succeeded" >&2; exit 1; fi
podman ps --filter label=com.docker.compose.project=acr-resilience --format '{{.Image}}' | grep -Eqx "(docker.io/library/|localhost/)?$IMAGE"
echo "resilience passed"
