#!/usr/bin/env bash
# Run Python in the toolbox container (the same image ./run.sh uses), from the repository root.
set -euo pipefail
cd "$(dirname "$0")/../.."
exec podman compose run --rm -T toolbox python "$@"
