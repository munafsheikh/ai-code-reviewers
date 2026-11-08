# Changelog

All notable changes are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning: SemVer.

## [Unreleased]

### Added
- Model registry expanded to 18 models across 11 families (Qwen2.5-Coder, Qwen3.5, Qwen3-Coder, Devstral Small 2, gpt-oss, Gemma 4, Phi-4-mini, Granite 3.3, Llama 3.2, DeepSeek-Coder-V2-Lite, Codestral), each with license class, size, architecture, Hugging Face id and sources.
- License-class policy enforcement (`allowed_license_classes`); new `evaluation` policy for benchmarking non-production weights.
- `laptop` and `gpu` profiles; `acr models recommend --ram-mb N [--policy P]`; `acr bench --policy`; `ACR_MEMORY_BUDGET_MB`.
- `Model matrix` workflow: pulls each model on a runner, records digests, benchmarks through the model, publishes a comparison.
- OpenAI-compatible servers (vLLM, LM Studio, LocalAI, llama.cpp) receive the manifest's Hugging Face id.
- Model selection guide.
- Companion rules (`[[companions]]`): diff-level checks that one kind of change travels with another. New `maintainability.docs` skill (`DOC-001`…`DOC-004`) blocks (major) build/CI/deploy, make target, CLI/env and contract changes made without documentation.
- Docker Hub publishing (`Images` workflow): shared base image plus layered reviewer, toolbox and fake-runtime images, multi-arch and signed; `make images`.

### Changed
- Ollama runtime pinned to 0.40.11 (newer model families need it).
- Single multi-stage Dockerfile replaces `Dockerfile.toolbox`; the toolbox now builds on the slim base (+ git). Compose runs the fake runtime from its own image target.
- Release builds arm64 under QEMU.

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
