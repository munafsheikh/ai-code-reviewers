#!/bin/sh
# One-shot model download with bounded retries. Never blocks the reviewer:
# on persistent failure it logs a structured error and exits 0, and the
# reviewer runs rules-only (reported as `degraded` in every result).
set -u
attempts="${PULL_ATTEMPTS:-3}"
delay=5
for model in $MODELS; do
  n=1
  while :; do
    if ollama pull "$model"; then
      echo "{\"level\":\"info\",\"component\":\"model-init\",\"action\":\"model_pulled\",\"model\":\"$model\"}"
      break
    fi
    if [ "$n" -ge "$attempts" ]; then
      echo "{\"level\":\"error\",\"component\":\"model-init\",\"action\":\"model_pull_failed\",\"model\":\"$model\",\"attempts\":$n}" >&2
      break
    fi
    echo "{\"level\":\"warn\",\"component\":\"model-init\",\"action\":\"retry\",\"model\":\"$model\",\"attempt\":$n,\"delay_s\":$delay}" >&2
    sleep "$delay"; n=$((n + 1)); delay=$((delay * 2))
  done
done
ollama list || true
exit 0
