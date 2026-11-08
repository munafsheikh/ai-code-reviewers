# Operations runbook

## Start, check, stop

| Task | Command |
|---|---|
| Start with a local model | `make up` (reviewer + Ollama + model pull; waits for health) |
| Start without weights (tests/demo) | `make up-test` |
| Health / readiness | `curl -s 127.0.0.1:8088/healthz` · `curl -s 127.0.0.1:8088/readyz` |
| Metrics (Prometheus text) | `curl -s 127.0.0.1:8088/metrics` |
| Review a diff | `make review DIFF=change.patch` or `git diff main... \| docker compose run --rm -T reviewer review` |
| Stop | `make down` (volumes kept) |
| Logs | `make logs` — JSON lines; `component` is `http`, `recovery`, `model-init`, `watchdog`, `deploy` |

`/readyz` returns `ready`, or `degraded` when the runtime is down or a configured model is
missing (`missing_models`). Degraded reviews still run rules and say so in every output.

## Self-healing (bounded)

| Failure | Detection | Automatic action | Bound | Audit |
|---|---|---|---|---|
| Container exits | Docker | `restart: unless-stopped` | Docker backoff | `docker events` |
| Container unhealthy | healthcheck | `make watchdog` restarts it | `MAX_RESTARTS` per `WINDOW_S` (3/h), then circuit opens + diagnostics, exit 1 | `out/watchdog/audit.log` |
| Runtime transient error (5xx, timeout, refused) | wrapper | retry with exponential backoff | `retry.attempts`, `max_delay_s`, review deadline | `recovery_events[]` in result |
| Repeated runtime failures | circuit breaker | stop calling for `cooldown_s`, then half-open probe | `failure_threshold` | `recovery_events[]` |
| Runtime/model unavailable | health / 404 | rules-only fallback (`degraded: true`) or exit 2 under `strict` | — | `fallback_rules_only` |
| Corrupt cache entry | sha256 check | evict + recompute | per entry | `cache_entry_evicted` |
| Model digest mismatch | `/api/tags` digest vs manifest | disable model for the run | — | `model_integrity_mismatch` |
| Stalled review | `review_timeout_s` deadline | skip remaining calls | per review | `review_deadline_exceeded` |
| Failed model download | `model-init` | retry 3× with backoff, then continue rules-only | 3 attempts | `model_pull_failed` |
| Failed deployment | `up --wait` / smoke | roll back to last verified image, keep diagnostics | 1 rollback | `out/deploy/` |

Nothing in this table changes policy, credentials or images, and nothing deletes data.
Schedule the watchdog with cron or a systemd timer, e.g. `*/5 * * * * make -C /opt/acr watchdog`.

## Deploy and roll back (test environment)

```bash
make build IMAGE=acr-reviewer:candidate
make deploy-test IMAGE=acr-reviewer:candidate     # smoke-tested; auto-rollback on failure
make rollback                                     # manual rollback to last verified
infrastructure/deployment/teardown.sh             # destroy the disposable environment
```

State (`last_verified`, history) lives in `out/deploy/state.json`. Releases are signed with
cosign keyless signing; `deploy.yml` refuses unsigned GHCR images.

See also [troubleshooting](troubleshooting.md).
