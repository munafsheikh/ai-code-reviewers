# Changelog

All notable changes are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning: SemVer.

## [Unreleased]

### Added
- Rule analyzers: `analyzer = "<id>"` on a rule confirms (reported `verified`) or rejects each regex candidate with a deterministic, stdlib-only check; `analyzer_fallback` decides undecidable candidates. Shipped: `python.http-without-timeout`, `python.sql-built-string`, `shell.unquoted-expansion`. Rule examples are validated through the analyzer.
- `lang.shell.core` 1.0.0 (deterministic only): SH-001 unquoted expansion, SH-002 unguarded `rm -r` on a variable path, SH-003 `curl | sh`, SH-004 unchecked `cd`, SH-005 `eval` of a variable, SH-006 world-writable `chmod`. Added to the `balanced` profile.
- `INJ-006` (Python): SQL built with an f-string, `%`, `+` or `.format()`, including through a local variable; covers f-strings with quoted placeholders that INJ-001 misses.
- `JAVA-017` (`BigDecimal.equals`) and `JAVA-018` (credential written to a log).
- `benchmarks/experiments/tiny-verify`: candidate → verify experiment (9 checks, 90 labelled cases, 5 models from 135M to 1.5B) with raw results.
- Benchmark fixtures `shell-pitfalls` and `python-ast-verified`.

### Changed
- `PY-007` (HTTP call without timeout) reads the whole call through its analyzer: multi-line calls that pass `timeout=` are no longer flagged, confirmed ones are reported `verified`.
- Validation applies `unless` per line for multi-line examples of line-scoped rules, as the engine does.

### Fixed
- `PY-003` (`is` with a literal) no longer matches prose such as "recall is 1.0 by construction" in docstrings: the literal must end the expression.

## [0.10.1] - 2026-11-25

### Security
- `libzstd1` upgraded to `1.5.7+dfsg-1+deb13u1` in the image `base` stage (CVE-2026-124851, HIGH) until the pinned `python:3.13-slim` carries the fix.

### Fixed
- Model discards are now explained: parse stats, the `model_output` audit line and the PR comment carry a reason per discard (`path_not_in_diff`, `missing_path`, `invalid_severity`, `missing_title`, `not_an_object`) plus up to three truncated samples.
- Model completion cache no longer fails on read-only containers: the GitHub action, Azure pipeline and Firefly gate set `ACR_CACHE_DIR=/tmp/acr-cache` on a `/tmp` tmpfs.

## [0.10.0] - 2026-11-25

### Security
- Base image `python:3.13-slim` bumped to `sha256:7249d558…`; expired `zlib1g` exceptions (CVE-2026-85091, CVE-2026-76844) removed from `policies/security/trivyignore`.

### Added
- `lang.python.core` 1.1.0: 14 Python rules (`PY-003`…`PY-016`): `is` with a literal, `== None`, `open()` without `with`, naive/deprecated UTC datetimes, `requests`/`httpx` calls without a timeout, blocking calls inside `async def`, unreferenced `create_task`, `random` for secrets, MD5/SHA-1 without `usedforsecurity=False`, `tempfile.mktemp`, star imports, blanket `# type: ignore`/`# noqa`, re-raise without `from`, 0o777 permissions. Also reviews `*.pyi`. The model prompt now covers correctness, resources, concurrency, Python-specific security, typing and performance, and skips what the rules already flag. Benchmark fixture `python-pitfalls`.
- `lang.java.core` 1.1.0: 13 Java rules (`JAVA-004`…`JAVA-016`): catching Throwable/Error, InterruptedException without restoring the interrupt, `lock()` outside try/finally, static `SimpleDateFormat`, `double`/`float` money, `BigDecimal` from a double, `Random` for secrets, MD5/SHA-1/DES/RC4/ECB, discarded exception cause, `@Transactional` on private/final methods, field injection, concatenated log messages, `newCachedThreadPool`. The model prompt now also covers money/time handling, concurrency, collections, Spring/JPA proxies and N+1, and XXE, and skips what the rules already flag. Benchmark fixture `java-pitfalls`.

## [0.9.0] - 2026-11-22

### Changed
- Development and CI tasks run in the toolbox through the `dev` Compose service: `docker compose run --rm dev <task>` (`help` lists them; tasks in `infrastructure/tasks.py`). Docker is the only host requirement. The toolbox image now carries the Docker CLI, Compose and Buildx, and tasks drive the host's Docker through its socket.

### Removed
- `Makefile` and `infrastructure/scripts/py.sh`: use the `dev` service tasks (e.g. `make ci` is `docker compose run --rm dev ci`, `make build IMAGE=x` is `... dev build --image x`).

## [0.8.0] - 2026-11-22

### Added
- Minimum confidence: findings below it are left out of the report and cannot block. Resolved from `--min-confidence` (`acr review`, `acr merge`, action input `min-confidence`), then `ACR_MIN_CONFIDENCE`, then the policy's `[gate] min_confidence` (every shipped policy: `low`), then the built-in default `low`. Results record the minimum, its source and the hidden findings by severity in `run.confidence`; the report prints them when the minimum is above `low`. `acr validate` checks policy confidence values.

## [0.7.0] - 2026-11-22

### Added
- Model runtime image `munafsheikh/ai-code-reviewers-runtime` (Dockerfile `runtime` target): Ollama's CPU build with `qwen2.5-coder:1.5b` baked in at build time, so running it downloads nothing. 221 MB plus the model instead of the 8.4 GB Ollama image (GPU libraries dropped); non-root, read-only, `OLLAMA_NO_CLOUD=1`. `runtime-gpu` target for CUDA/ROCm hosts; `make runtime MODELS="..."` for other models.
- Team review instructions at run time: `*.md` in `/etc/acr/instructions.d` (`ACR_INSTRUCTIONS_DIR`), `acr review --instructions FILE`, `ACR_INSTRUCTIONS`. Given to the model as trusted guidance outside the untrusted-diff fence, bounded, and recorded by name and SHA-256 in `run.instructions`. GitHub action input `instructions`.
- Operator skills: extra skill directories in `/etc/acr/skills.d` and `ACR_SKILLS_DIRS`; `--skills` / `ACR_SKILLS` selects skills per run.
- `acr merge`: combines reviews of one change from parallel lanes into one result (findings de-duplicated, coverage judged across lanes, one gate, `run.lanes`). GitHub action inputs `skills`, `merge-results`, `lane-names`; `base-ref` accepts a commit SHA for push events.
- `make prove-offline`: shows on your machine that the reviewer and runtime cannot reach the internet or resolve names, and that a model review still completes.
- Documentation site (MkDocs, `infrastructure/docs/mkdocs.yml`, built in the toolbox with `make docs-site`) published to GitHub Pages by the `Docs site` workflow as a Release stage; new guides: getting started, code review examples, customizing reviews, proving code stays local, CI/CD pipeline (with diagram, also in the README).
- Examples: `examples/custom-image` (reviewer image with team instructions and a team rule) and `examples/compose` (stand-alone stack from the published images on an internal network).

### Changed
- CI reviews this project's own changes in three parallel lanes (code, security, docs) with the local model, merged into one gate, on pull requests and on pushes to `main`; Release (and deployment) follows only green, reviewed commits.
- Compose builds the model runtime with the model baked in and attaches it to the internal network only; `compose.yaml` maps `config/instructions.d` and `config/skills.d` into the reviewer.
- The GitHub action defaults to the release's runtime image (no model download) and skips pulls for models already in the image.

### Removed
- `model-init` Compose service, `infrastructure/scripts/pull-model.sh` and the `llm-models` volume: models are baked into the runtime image.

### Fixed
- Ollama no longer tries to contact `ollama.com` from the runtime (cloud model metadata and recommendations).

## [0.6.0] - 2026-11-21

### Added
- `AGENTS.md`: entry point for AI coding agents, linking to the documents that own each fact, with agent-only rules. `CLAUDE.md`, `GEMINI.md` and `.github/copilot-instructions.md` are symlinks to it; the README, CONTRIBUTING, SECURITY and the architecture, development, operations and security docs link back. `validate` requires it.

### Fixed
- The link checker skips symlinked Markdown files, whose relative links resolve from their target.

## [0.5.0] - 2026-11-19

### Added
- Refinement-stage review of GitHub issues: `acr review --issue FILE|-` takes `gh issue view N --json number,title,body,labels,url`, a REST issue or an `issues` webhook payload and reviews it with the same rules, model, gate and outputs as a diff. New skill `refinement.issue` (REF-001, REF-002, REF-101 to REF-105): untestable wording, placeholders, missing acceptance criteria, bug reports without steps to reproduce or expected vs actual, image-only descriptions, empty descriptions.
- Expectation rules (`[[expects]]` in `skill.toml`): document-level absence checks with optional `when` / `unless` scope and self-testing `examples.flag` / `examples.pass`.
- Lifecycle artifacts: work items are reviewed as virtual `@` paths (`@issue/42`). Code skills never reach them; coverage reports them as kind `artifact` and requires their stage's category. Findings carry `location.anchor` (the section heading) and link to the issue.

## [0.4.0] - 2026-11-15

### Added
- Pull requests to this repository are reviewed by a real local model: CI self-review runs the `balanced` profile (rules + Ollama `qwen2.5-coder:1.5b` on the CPU runner) instead of rules only, and fails if the model did not run.
- GitHub action input `require-model` (fail when the review ran degraded) and output `degraded`.

### Fixed
- Test-environment deploy and rollback build the fake model runtime when the host lacks it; the first automatic release (0.3.0) published everything but failed at deploy.

## [0.3.0] - 2026-11-15

### Added
- Automatic releases: every green CI run on `main` plans the next version from `[Unreleased]` (or a `release:*` PR label), bumps every version reference, re-tests, commits and tags `vX.Y.Z`, publishes the signed GHCR image, the GitHub release and all Docker Hub images, then deploys the test environment. `infrastructure/scripts/release.py` with `make release-plan|apply|check|notes|image-tags`.

### Changed
- One tooling model: Docker and make are the only host requirements; every make target runs native commands in the `toolbox` image, CI calls only make targets, and `py.sh` runs in the toolbox instead of a separate Python image. The minimum-Python job builds the toolbox on Python 3.11 instead of using a host interpreter.
- `Deploy` is called by `Release` after publishing, instead of running after every Release run.

### Removed
- `LOCAL=1` host-venv mode and `make dev`.
- `Tag version` workflow: `Release` tags and publishes (manual `version` input for backfills).

### Fixed

- The Tag version workflow was invalid YAML, so GitHub could not run it; a test now parses every workflow and action file.

## [0.2.0] - 2026-11-08

### Added
- Model registry expanded to 18 models across 11 families (Qwen2.5-Coder, Qwen3.5, Qwen3-Coder, Devstral Small 2, gpt-oss, Gemma 4, Phi-4-mini, Granite 3.3, Llama 3.2, DeepSeek-Coder-V2-Lite, Codestral), each with license class, size, architecture, Hugging Face id and sources.
- License-class policy enforcement (`allowed_license_classes`); new `evaluation` policy for benchmarking non-production weights.
- `laptop` and `gpu` profiles; `acr models recommend --ram-mb N [--policy P]`; `acr bench --policy`; `ACR_MEMORY_BUDGET_MB`.
- `Model matrix` workflow: pulls each model on a runner, records digests, benchmarks through the model, publishes a comparison.
- OpenAI-compatible servers (vLLM, LM Studio, LocalAI, llama.cpp) receive the manifest's Hugging Face id.
- Model selection guide.
- Traceable reviews: every finding links to the exact lines at the reviewed commit and to its rule documentation (`docs/generated/rules.md`, versioned anchors); review comments link the commit, the CI run and its report artifacts; JSON results carry `links`, SARIF rules carry `helpUri`. The GitHub action uploads the reports as an artifact and reviews the PR head commit (new `head-ref` input), so permalinks survive the PR.
- Companion rules (`[[companions]]`): diff-level checks that one kind of change travels with another.
- `documentation` skill category: `documentation.sync` (`DOC-001`…`DOC-004`, major) blocks build/CI/deploy, make target, CLI/env and contract changes made without docs; `documentation.content` (`DOC-101`…`DOC-104` + model prompt) reviews the docs themselves. `MNT-004` flags conflict markers in code.
- Review coverage: `run.coverage` records which categories examined each changed file; `require_coverage` (default and strict policies) blocks when a code file got no code check or a doc file no documentation check.
- CI self-review is enforced and now reviews tests (except the rule-sample files).
- Docker Hub publishing (`Images` workflow): shared base image plus layered reviewer, toolbox and fake-runtime images, multi-arch and signed; `make images`.

### Changed
- Ollama runtime pinned to 0.40.11 (newer model families need it).
- Docs and CI templates reference release tags (`@v0.2.0`, image `0.2.0`); a `Tag version` workflow creates verified tags.
- Single multi-stage Dockerfile replaces `Dockerfile.toolbox`; the toolbox now builds on the slim base (+ git). Compose runs the fake runtime from its own image target.
- Release builds arm64 under QEMU.

### Fixed
- `Images` workflow passes the base image digest between jobs instead of the full reference (GitHub drops outputs containing a secret value, e.g. a namespace equal to `DOCKERHUB_USERNAME`).
- Empty `LLM_MODEL` / `ACR_SMALL_MODEL` no longer disable the profile's model outside the legacy profile; the GitHub action no longer forwards an empty `LLM_MODEL`.
- Model-matrix planner no longer requires git in its container.

## [0.1.0] - 2026-11-08

### Added
- Review engine: diff parsing, rules engine (line and block scope), model routing (small/large
  tiers, memory budget, fallback), bounded retry, circuit breaker, integrity-checked cache, deadlines.
- Contracts and JSON Schemas: `acr.result/v1`, `acr.skill/v1`, `acr.model/v1`, `acr.wrapper/v1`, `acr.profile/v1`.
- Outputs: JSON, SARIF 2.1.0, Markdown, legacy SEVERITY text.
- Wrappers: Ollama, llama.cpp (OpenAI-compatible), CLI subprocess, reference echo wrapper.
- 12 skills / 26 rules; 3 model manifests (qwen2.5-coder 0.5B, 1.5B, 7B); 5 profiles; 3 policies.
- `legacy` profile: behaviour-compatible with Firefly's `ReviewGate.java` (golden-tested).
- CLI (`review`, `validate`, `bench`, `models`, `skills`, `health`, `serve`, `docs`, `evolve`) and HTTP service.
- Docker image (non-root, read-only, stdlib-only) and Compose stack with health checks.
- Docker-first tooling: pinned toolbox image runs validate, lint, tests, docs and benchmarks; helper scripts run Python in a pinned container.
- CI, security (levels 1–3), model end-to-end, release (SBOM, signing), deploy with rollback, scheduled automation.
- Integrations: GitHub Actions, Azure DevOps, GitLab, Firefly.
