# Agent guide

Entry point for AI coding agents. Every fact lives in the linked document that owns it; this file only maps them and adds the rules that apply to agents alone. Humans start at the [README](README.md).

## Before any change

- What the platform is, quick start, how it works: [README](README.md)
- How to verify and land a change (`make ci`, generated docs, gates, commit style): [CONTRIBUTING](CONTRIBUTING.md)
- Adding rules, companions, expectations, skills or models: [extending](docs/development/extending.md)

## When relevant

- Components, review flow, design decisions: [architecture overview](docs/architecture/overview.md)
- Using it (images, examples, customization, privacy proof): [getting started](docs/usage/getting-started.md), [customize](docs/usage/customize.md), [prove code stays local](docs/usage/privacy.md)
- CI/CD and releases: [pipeline](docs/architecture/pipeline.md)
- Running, deploying, releasing: [runbook](docs/operations/runbook.md), [troubleshooting](docs/operations/troubleshooting.md)
- Choosing a model: [model selection](docs/operations/model-selection.md)
- Untrusted input, secrets, reporting issues: [threat model](docs/security/threat-model.md), [SECURITY](SECURITY.md)
- Catalogues of skills, rules, models, profiles, schemas, CLI and configuration: [docs/generated](docs/generated/skills.md)

## Agent rules

- `skills/` in this repository holds review skills for the reviewer models (`skill.toml` + `prompt.md`). It does not hold instructions for coding agents.
- `docs/generated/` is generated from the source definitions. Never edit it; regenerate it as [CONTRIBUTING](CONTRIBUTING.md) says.
- Never weaken a gate, threshold or scanner to get a green build; follow the exception process in [CONTRIBUTING](CONTRIBUTING.md).
- Working files (plans, notes, logs) go in `.scratch/`. Never create files at the repository root.
- `CLAUDE.md`, `GEMINI.md` and `.github/copilot-instructions.md` are symlinks to this file. Edit this file only.
