# Changelog

All notable changes are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning: SemVer.

## [Unreleased]

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
- CI, security (levels 1–3), model end-to-end, release (SBOM, signing), deploy with rollback, scheduled automation.
- Integrations: GitHub Actions, Azure DevOps, GitLab, Firefly.
