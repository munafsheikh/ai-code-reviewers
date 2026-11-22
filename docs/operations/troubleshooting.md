# Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Result says `degraded: true`, `runtime unavailable` | runtime not started or wrong host | `docker compose --profile model up -d --wait`; check `ACR_MODEL_HOST`; `acr health` |
| `egress to 'x' is not allowed` | runtime host not allow-listed | use a compose service name / loopback, or set `ACR_ALLOWED_HOSTS=x` deliberately |
| `HTTP 404 ... model ... not found` | the runtime image does not contain that model | rebuild it with the model: `docker compose run --rm dev runtime --models "<ref>"` (or `ACR_RUNTIME_MODELS=... docker compose --profile model build llm-runtime`), or use a model it has (`docker exec <runtime> ollama list`) |
| Runtime build fails pulling the model | no internet / registry blocked at build time | build (or pull `munafsheikh/ai-code-reviewers-runtime`) on a connected host, `docker save` / `docker load` it; or run the `offline` profile |
| `model_integrity_mismatch` | runtime has a different build of the model | re-verify provenance; `acr models verify`; update the manifest digest via PR |
| Exit code 2 | strict policy + infra failure, unreadable diff, or schema violation | read stderr; `-v` prints structured recovery logs |
| Review slow / `budget_limited` | diff larger than `max_diff_chars × max_model_calls` | use `deep` profile, or review per directory with `--paths` |
| `circuit open` | runtime failed repeatedly | wait `cooldown_s` or fix the runtime; the next call half-opens |
| Docker build fails on corporate network | proxy/CA not visible to build containers | build with `--network host` and proxy build args; scans accept `SCAN_DOCKER_ARGS` |
| `validate` fails on a rule example | a regex change broke its declared behaviour | fix the pattern or the example; examples are the rule's unit tests |

Diagnostics: `acr review -v` (recovery events on stderr), `out/deploy/diagnostics-*`,
`out/watchdog/diagnostics-*`, and the `run.recovery_events` array in every JSON result.

<sub>For AI coding agents: [agent guide](../../AGENTS.md).</sub>
