#!/usr/bin/env bash
# Run Python in the toolbox image (the same image every make target uses), with the current
# directory mounted at the same path, so scripts and `python -c` snippets need no host Python.
set -euo pipefail
image=$(make -s --no-print-directory -C "$(dirname "$0")/../.." toolbox-ref)
exec docker run --rm -i -u "$(id -u):$(id -g)" -e PYTHONDONTWRITEBYTECODE=1 -v "$PWD:$PWD" -w "$PWD" "$image" python "$@"
