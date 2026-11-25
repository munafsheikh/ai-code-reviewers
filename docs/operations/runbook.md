# Operations runbook

## Start, check, stop

| Task | Command |
|---|---|
| Start with a local model | `docker compose --profile model up -d --build --wait` (reviewer + runtime with the model baked in) |
| Start without weights (tests/demo) | `docker compose --profile test up -d --build --wait` |
| Health / readiness | `curl -s 127.0.0.1:8088/healthz` · `curl -s 127.0.0.1:8088/readyz` |
| Metrics (Prometheus text) | `curl -s 127.0.0.1:8088/metrics` |
| Review a diff | `docker compose run --rm -T reviewer review < change.patch` or `git diff main... \| docker compose run --rm -T reviewer review` |
| Stop | `docker compose --profile model --profile test down` (volumes kept) |
| Logs | `docker compose logs -f` — JSON lines; `component` is `http`, `recovery`, `watchdog`, `deploy` |

`/readyz` returns `ready`, or `degraded` when the runtime is down or a configured model is
missing (`missing_models`). Degraded reviews still run rules and say so in every output.

## Self-healing (bounded)

| Failure | Detection | Automatic action | Bound | Audit |
|---|---|---|---|---|
| Container exits | Docker | `restart: unless-stopped` | Docker backoff | `docker events` |
| Container unhealthy | healthcheck | the `watchdog` task restarts it | `MAX_RESTARTS` per `WINDOW_S` (3/h), then circuit opens + diagnostics, exit 1 | `out/watchdog/audit.log` |
| Runtime transient error (5xx, timeout, refused) | wrapper | retry with exponential backoff | `retry.attempts`, `max_delay_s`, review deadline | `recovery_events[]` in result |
| Repeated runtime failures | circuit breaker | stop calling for `cooldown_s`, then half-open probe | `failure_threshold` | `recovery_events[]` |
| Runtime/model unavailable | health / 404 | rules-only fallback (`degraded: true`) or exit 2 under `strict` | — | `fallback_rules_only` |
| Corrupt cache entry | sha256 check | evict + recompute | per entry | `cache_entry_evicted` |
| Model digest mismatch | `/api/tags` digest vs manifest | disable model for the run | — | `model_integrity_mismatch` |
| Stalled review | `review_timeout_s` deadline | skip remaining calls | per review | `review_deadline_exceeded` |
| Failed deployment | `up --wait` / smoke | roll back to last verified image, keep diagnostics | 1 rollback | `out/deploy/` |

Nothing in this table changes policy, credentials or images, and nothing deletes data.
Schedule the watchdog with cron or a systemd timer, e.g. `*/5 * * * * cd /opt/acr && docker compose run --rm -T dev watchdog`.

## Deploy and roll back (test environment)

```bash
docker compose run --rm dev build --image acr-reviewer:candidate
docker compose run --rm dev deploy-test --image acr-reviewer:candidate   # smoke-tested; auto-rollback on failure
docker compose run --rm dev rollback                                     # manual rollback to last verified
docker compose run --rm dev teardown                                     # destroy the disposable environment
```

State (`last_verified`, history) lives in `out/deploy/state.json`. Releases are signed with
cosign keyless signing; `deploy.yml` refuses unsigned GHCR images.

## Releases

Releases are automatic. Every green CI run on `main` goes through the `Release` workflow:

1. **Plan** (`release plan`): the next version comes from the CHANGELOG `[Unreleased]`
   section. `### Removed` or "BREAKING" means major (minor while 0.x). `### Added`, `### Changed`
   or `### Deprecated` means minor. `### Fixed` or `### Security` means patch. An empty section
   means no release. A label on the merged PR overrides it: `release:major`, `release:minor`,
   `release:patch` or `release:skip`. To batch several merges into one release, label all but
   the last `release:skip`: their entries stay under `[Unreleased]` and ship with the next
   unlabelled merge. Do not merge to `main` while a release's bump job is running: its push of
   `Release X.Y.Z` is a fast-forward and fails if `main` moved.
2. **Bump** (`release apply X.Y.Z`): rewrites `pyproject.toml`,
   `orchestrator.__version__`, the CHANGELOG (`[Unreleased]` becomes `[X.Y.Z] - date`) and the
   tag and image references in `integrations/`. The `ci` task then re-tests the bumped tree, and
   `Release X.Y.Z` plus the tag `vX.Y.Z` are pushed to `main` together.
3. **Publish**: `release check`, the vulnerability gate, SBOM, the reviewer image to GHCR
   (signed and attested), and a GitHub release with the CHANGELOG section as notes.
4. **Images**: base, reviewer, toolbox and fake-runtime go to Docker Hub as `X.Y.Z`, `X.Y` and
   `latest`. Every green `main` also publishes `edge` and `sha-<12>`.
5. **Deploy**: a disposable test environment, with auto-rollback.

Manual runs: `Release` → *Run workflow* with `bump` forces a level. `version` (+ `commit`) tags
and publishes an existing version, e.g. to backfill `0.2.0`. A `vX.Y.Z` tag pushed by a person
is tested and published.

Requirements: github-actions must be able to push to `main` (no branch protection blocking it,
or a bypass for it). Docker Hub needs the `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN` secrets.
Review gates run before any of this: a commit that fails CI, including the enforced
self-review, is never released.

See also [troubleshooting](troubleshooting.md).

<sub>For AI coding agents: [agent guide](../../AGENTS.md).</sub>
