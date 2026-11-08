# Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Result says `degraded: true`, `runtime unavailable` | runtime not started or wrong host | `make up`; check `ACR_MODEL_HOST`; `acr health` |
| `egress to 'x' is not allowed` | runtime host not allow-listed | use a compose service name / loopback, or set `ACR_ALLOWED_HOSTS=x` deliberately |
| `HTTP 404 ... model ... not found` | model not pulled | `docker compose --profile model run --rm model-init`, or `ACR_PULL_MODELS=...` |
| `model_pull_failed` in model-init logs | no internet / registry blocked | pull on a connected host and copy the `llm-models` volume, or run `offline` profile |
| `model_integrity_mismatch` | runtime has a different build of the model | re-verify provenance; `acr models verify`; update the manifest digest via PR |
| Exit code 2 | strict policy + infra failure, unreadable diff, or schema violation | read stderr; `-v` prints structured recovery logs |
| Review slow / `budget_limited` | diff larger than `max_diff_chars × max_model_calls` | use `deep` profile, or review per directory with `--paths` |
| `circuit open` | runtime failed repeatedly | wait `cooldown_s` or fix the runtime; the next call half-opens |
| Docker build fails on corporate network | proxy/CA not visible to build containers | build with `--network host` and proxy build args; scans accept `SCAN_DOCKER_ARGS` |
| `validate` fails on a rule example | a regex change broke its declared behaviour | fix the pattern or the example; examples are the rule's unit tests |

Diagnostics: `acr review -v` (recovery events on stderr), `out/deploy/diagnostics-*`,
`out/watchdog/diagnostics-*`, and the `run.recovery_events` array in every JSON result.
