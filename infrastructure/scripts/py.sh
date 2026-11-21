#!/usr/bin/env bash
# Run Python in the toolbox container (the same image ./run.sh uses), from the repository root.
set -euo pipefail
cd "$(dirname "$0")/../.."
# Build once if missing (output to stderr, so stdout stays clean for callers that capture it).
podman image exists "${ACR_TOOLBOX_IMAGE:-acr-toolbox:local}" || podman compose build toolbox >&2
exec podman compose run --rm -T toolbox python "$@"
