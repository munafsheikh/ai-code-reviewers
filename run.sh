#!/usr/bin/env bash
# Runs a repository task in the toolbox container: ./run.sh TASK [ARGS]  (./run.sh -h lists tasks).
# Podman is the only host requirement; the task logic lives in infrastructure/scripts/tasks.py.
set -eu
cd "$(dirname "$0")"
exec podman compose run --rm --build -T toolbox python infrastructure/scripts/tasks.py "$@"
