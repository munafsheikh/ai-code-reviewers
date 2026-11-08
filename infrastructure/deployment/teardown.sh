#!/usr/bin/env bash
# Destroy the disposable test environment, including its volumes.
set -euo pipefail
cd "$(dirname "$0")/../.."
docker compose -p "${ACR_TEST_PROJECT:-acr-test}" --profile test down --volumes --remove-orphans
