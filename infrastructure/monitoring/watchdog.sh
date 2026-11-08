#!/usr/bin/env bash
# Bounded self-healing pass: restart unhealthy/exited services of a compose project,
# at most MAX_RESTARTS per service per WINDOW_S. When the budget is exhausted it
# stops restarting (circuit open), writes a diagnostics bundle and exits 1 so a
# scheduler/CI job can open an issue. Every action is a JSON audit line.
# It never changes configuration, images or volumes.
set -euo pipefail
cd "$(dirname "$0")/../.."
PROJECT="${COMPOSE_PROJECT:-ai-code-reviewers}"
MAX_RESTARTS="${MAX_RESTARTS:-3}"
WINDOW_S="${WINDOW_S:-3600}"
STATE_DIR="${WATCHDOG_STATE:-out/watchdog}"
mkdir -p "$STATE_DIR"
now=$(date +%s)
rc=0
audit() { echo "{\"ts\":\"$(date -u +%FT%TZ)\",\"component\":\"watchdog\",\"project\":\"$PROJECT\",$1}" | tee -a "$STATE_DIR/audit.log"; }

for cid in $(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT"); do
  svc=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$cid")
  state=$(docker inspect --format '{{.State.Status}}' "$cid")
  health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")
  [ "$svc" = "model-init" ] && continue               # one-shot job, exits by design
  if [ "$health" != "unhealthy" ] && [ "$state" = "running" ]; then continue; fi
  hist="$STATE_DIR/$svc.restarts"
  touch "$hist"
  recent=$(awk -v cutoff=$((now - WINDOW_S)) '$1 >= cutoff' "$hist" | wc -l)
  if [ "$recent" -ge "$MAX_RESTARTS" ]; then
    diag="$STATE_DIR/diagnostics-$svc-$now"
    mkdir -p "$diag"
    # State only: full inspect output would include environment variables.
    docker inspect --format "{{json .State}}" "$cid" > "$diag/state.json" 2>&1 || true
    docker logs --tail 500 "$cid" > "$diag/logs.txt" 2>&1 || true
    audit "\"action\":\"circuit_open\",\"service\":\"$svc\",\"state\":\"$state\",\"health\":\"$health\",\"restarts_in_window\":$recent,\"diagnostics\":\"$diag\""
    rc=1
    continue
  fi
  audit "\"action\":\"restart\",\"service\":\"$svc\",\"state\":\"$state\",\"health\":\"$health\",\"attempt\":$((recent + 1))"
  echo "$now" >> "$hist"
  timeout 60 docker restart "$cid" >/dev/null || { audit "\"action\":\"restart_failed\",\"service\":\"$svc\""; rc=1; }
done
exit $rc
