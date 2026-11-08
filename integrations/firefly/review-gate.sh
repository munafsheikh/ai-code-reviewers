#!/usr/bin/env bash
# Local / pre-commit review for Firefly using ai-code-reviewers.
#   git diff --cached | tools/review-gate/review-gate.sh            # structured (fast profile)
#   git diff --cached | ACR_PROFILE=legacy LLM_MODEL=qwen2.5-coder:1.5b tools/review-gate/review-gate.sh
# Uses a local checkout when ACR_HOME is set, otherwise the published container image.
set -euo pipefail
PROFILE="${ACR_PROFILE:-fast}"
FORMAT="${ACR_FORMAT:-legacy}"
IMAGE="${ACR_IMAGE:-ghcr.io/munafsheikh/ai-code-reviewers:0.1.0}"
HOST="${LLM_HOST:-${ACR_MODEL_HOST:-http://host.docker.internal:11434}}"
if [ -n "${ACR_HOME:-}" ]; then
  exec env PYTHONPATH="$ACR_HOME" ACR_MODEL_HOST="${LLM_HOST:-${ACR_MODEL_HOST:-http://127.0.0.1:11434}}" \
    python3 -m orchestrator review --profile "$PROFILE" --format "$FORMAT"
fi
exec docker run --rm -i --read-only --cap-drop ALL --add-host=host.docker.internal:host-gateway \
  -e ACR_MODEL_HOST="$HOST" -e LLM_MODEL="${LLM_MODEL:-}" "$IMAGE" review --profile "$PROFILE" --format "$FORMAT"
