#!/usr/bin/env bash
# Runs a repository task in the toolbox container: ./run.sh TASK [ARGS]  (./run.sh -h lists tasks).
# Podman is the only host requirement; the task logic lives in infrastructure/scripts/tasks.py.
set -eu
cd "$(dirname "$0")"
# Build output goes to stderr, so a task's stdout stays clean for callers that capture it.
podman compose build toolbox >&2
exec podman compose run --rm -T toolbox python infrastructure/scripts/tasks.py "$@"
