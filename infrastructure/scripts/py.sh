#!/usr/bin/env bash
# Docker-first Python runner for helper scripts: runs in the pinned Python image with the
# current directory mounted at the same path, so no host Python is required.
# ACR_LOCAL=1 uses the host python3 instead.
set -euo pipefail
if [ "${ACR_LOCAL:-0}" = "1" ]; then exec python3 "$@"; fi
exec docker run --rm -i -u "$(id -u):$(id -g)" -e PYTHONDONTWRITEBYTECODE=1 -v "$PWD:$PWD" -w "$PWD" \
  python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 python "$@"
