#!/usr/bin/env bash
# Prove that a review cannot send code anywhere: run it on a network with no route out and
# show that (1) neither container can reach the internet or resolve names, (2) the review
# still completes with the model, and (3) rules-only reviews need no network at all.
#   prove-offline.sh [REVIEWER_IMAGE] [RUNTIME_IMAGE] [DIFF]
# Exit 0 = every check passed. Run it on the machine where you review code.
set -uo pipefail
cd "$(dirname "$0")/../.."
REVIEWER="${1:-acr-reviewer:local}"
RUNTIME="${2:-acr-runtime:local}"
DIFF="${3:-examples/sample-repo/change.patch}"
NET="acr-proof-$$"
RT="acr-proof-runtime-$$"
fail=0
pass() { printf '  PASS  %s\n' "$1"; }
bad() { printf '  FAIL  %s\n' "$1"; fail=1; }
cleanup() { docker rm -f "$RT" >/dev/null 2>&1; docker network rm "$NET" >/dev/null 2>&1; }
trap cleanup EXIT

echo "Reviewer: $REVIEWER"
echo "Runtime:  $RUNTIME"
echo "Diff:     $DIFF"
echo
echo "1. Isolated network"
docker network create --internal "$NET" >/dev/null
[ "$(docker network inspect -f '{{.Internal}}' "$NET")" = "true" ] && pass "network $NET is internal (no gateway, no route to the internet)" || bad "network is not internal"

docker run -d --name "$RT" --network "$NET" --network-alias llm-runtime --read-only --tmpfs /tmp \
  --cap-drop ALL --security-opt no-new-privileges:true "$RUNTIME" >/dev/null || { bad "runtime failed to start"; exit 1; }
for _ in $(seq 1 60); do
  [ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$RT")" != "starting" ] && break
  sleep 2
done
nets=$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$RT")
[ "$nets" = "$NET " ] && pass "runtime is attached to $NET only" || bad "runtime networks: $nets"

echo
echo "2. No way out (probes from inside the containers)"
probe='import socket,sys
def tcp(h,p):
    try: socket.create_connection((h,p),timeout=4).close(); return True
    except OSError: return False
def dns(n):
    try: socket.getaddrinfo(n,443); return True
    except OSError: return False
ok = [tcp("1.1.1.1",443), tcp("8.8.8.8",53), dns("github.com"), dns("ollama.com")]
print(" ".join(map(str,ok))); sys.exit(1 if any(ok) else 0)'
if out=$(docker run --rm --network "$NET" --entrypoint python "$REVIEWER" -c "$probe" 2>&1); then
  pass "reviewer container: TCP to 1.1.1.1:443 and 8.8.8.8:53 refused, DNS for github.com and ollama.com fails"
else
  bad "reviewer container reached the outside: $out"
fi
if ! docker exec "$RT" bash -c true >/dev/null 2>&1; then
  bad "runtime container has no bash to probe from; cannot prove its isolation this way"
elif docker exec "$RT" bash -c 'timeout 4 bash -c "</dev/tcp/1.1.1.1/443"' >/dev/null 2>&1; then
  bad "runtime container reached 1.1.1.1:443"
else
  pass "runtime container: TCP to 1.1.1.1:443 refused"
fi

echo
echo "3. The review still works, with the model, inside the isolated network"
out_dir=$(mktemp -d)
chmod 0777 "$out_dir"
docker run --rm -i --network "$NET" --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges:true \
  -v "$out_dir:/out" -e ACR_MODEL_HOST=http://llm-runtime:11434 \
  "$REVIEWER" review --profile balanced --format json --out-dir /out < "$DIFF" >/dev/null 2>"$out_dir/log"
summary=$(docker run --rm -i --network none --entrypoint python "$REVIEWER" -c '
import json,sys
r=json.load(sys.stdin); run=r["run"]
print(r["gate"]["status"], str(run["degraded"]).lower(), ",".join(m["ref"] for m in run["models"]) or "-", run["calls"]["total"], run["source"]["files_reviewed"])' < "$out_dir/review.json" 2>/dev/null)
read -r gate degraded models calls files <<<"${summary:-error true - 0 0}"
if [ "$degraded" = "false" ] && [ "$models" != "-" ]; then
  pass "reviewed $files file(s) with model $models ($calls call(s)), gate: $gate"
else
  bad "review degraded or without a model (gate: $gate); see $out_dir/log"
fi

echo
echo "4. Rules-only review with no network interface at all (--network none)"
if docker run --rm -i --network none --read-only "$REVIEWER" review --profile offline --format json < "$DIFF" >/dev/null 2>&1 || [ $? -eq 1 ]; then
  pass "offline review completed with --network none"
else
  bad "offline review failed with --network none"
fi
rm -rf "$out_dir"

echo
if [ "$fail" -eq 0 ]; then echo "RESULT: PASS - the code under review could not leave this machine."; else echo "RESULT: FAIL"; fi
exit "$fail"
