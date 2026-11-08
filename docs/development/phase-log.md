# Implementation log (observed results)

Results below were observed when each phase was executed in the development sandbox on
2026-11-08 (Linux, Docker 29.9, Python 3.13). CI results are recorded by the workflows.

## Phase 1 — Discovery and extraction

Firefly's review capability is `tools/review-gate/ReviewGate.java` (single-file JDK program)
plus `.github/workflows/review-gate.yml` (Ollama service container, model pull, PR comment,
gate on exit code 1).

| Finding | Evidence |
|---|---|
| Generic: prompt, SEVERITY protocol, truncation at 24,000 chars, fail-open parsing, exit codes 0/1/2 | ReviewGate.java |
| Firefly-specific: `*.java` path filter, PR-comment marker, repository variables `LLM_RUNTIME_IMAGE`/`LLM_MODEL` | review-gate.yml |
| Defect: workflow references undefined `${LLM_BASE_URL}`; health check and pull lost their `/api/tags` and `/api/pull` paths (commit 870eec4) | review-gate.yml |
| Fragility: response parser matches the literal `"response":"` and silently fails open on whitespace-formatted JSON | characterisation run with spaced JSON |

Behaviour was recorded **before** re-implementation: `tests/regression/characterize_legacy.py`
ran the original Java gate against the fake runtime for 11 cases → `legacy_gate_golden.json`.
The `legacy` profile reproduces all 11 (stdout and exit code), the prompt is byte-identical
(sha256 `03e58eab…`), and the wire payload to `/api/generate` is identical (optional test
`LEGACY_REVIEWGATE=/path/ReviewGate.java`).

## Phase 2 — Standalone foundation

Engine, contracts, 4 wrappers (ollama, llama-cpp, cli, example-echo), 12 skills / 26 rules,
3 model manifests, 5 profiles, 3 policies, CLI (`review validate bench models skills health serve
docs evolve`), HTTP service, Compose stack. Image: 178 MB, uid 10001, read-only rootfs, pip removed.

## Phase 3 — Automated verification

- Tests: 114 passed, 1 skipped (needs JDK + ReviewGate.java), coverage ≥ 85 % (gate 80 %).
- `acr validate`: all checks pass; 3 warnings (model digests unpinned — see limitations).
- Offline benchmark: 8 fixtures, precision 1.0, recall 1.0, gate accuracy 1.0, stability 1.0.
- Compose e2e: health-gated startup, smoke, CLI container, non-root and read-only asserted.
- Scans (local): gitleaks pass, semgrep pass (6 rules), hadolint pass, trivy fs pass,
  trivy image pass after remediation (see [vulnerability baseline](../security/vulnerability-baseline.md)).

## Phase 4 — Delivery automation

`deploy.sh` verified a good image, then failed a deliberately broken image on its health
gate, captured diagnostics and rolled back to the last verified image (smoke-tested).
Release signing/publishing (`release.yml`) runs only on a tag in GitHub Actions; not executed here.

## Phase 5 — Operational resilience

Fault injection (unit + integration): transient 503 → retried; permanent 4xx → not retried;
circuit open/half-open; cache tamper → evicted; runtime down → rules-only; digest mismatch →
model disabled; budget and deadline limits audited. Compose: watchdog restarted a stopped
reviewer once, then opened its circuit and wrote diagnostics (`tests/end-to-end/resilience.sh`).
Real Ollama 0.12.6 ran healthy under `read_only` + `cap_drop: ALL`; the model pull failed
because the sandbox blocks `registry.ollama.ai`, and reviews degraded to rules-only as designed.

## Phase 6 — Continuous evolution (minimal)

`acr evolve` produces a prioritised proposal from local evidence (unbenchmarked rules,
unpinned models/images, expiring exceptions, benchmark regressions). The monthly workflow
files it as an issue. No automatic merges; no third-party skills/models are fetched.

## Known limitations

- No real model inference was executed in the sandbox (model registry unreachable). The
  `model-e2e` workflow runs Ollama + `qwen2.5-coder:0.5b` on GitHub-hosted runners.
- Model manifests are `candidate` with unpinned digests until `acr models verify --pin` runs on a
  trusted runtime; the `strict` policy refuses unpinned models.
- Model-tier thresholds in `policies/quality-gates/benchmarks.toml` are provisional until weekly
  evaluations accumulate evidence.
- The diff parser treats a removed line starting with `--- ` immediately followed by an added line
  starting with `+++ ` as a file header (rare).
