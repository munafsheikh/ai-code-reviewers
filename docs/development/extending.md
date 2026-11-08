# Extending the platform

## Add a rule (deterministic)

1. Add a `[[rules]]` entry to a skill's `skill.toml`: `id` (`ABC-123`, unique), `title`, `severity`,
   `confidence`, `pattern` (Python regex), optional `unless`, `languages`, `scope = "block"` for
   multi-line patterns, `explanation`, `remediation`, and **`examples.match` / `examples.no_match`**.
2. `python -m orchestrator validate` — every example is executed; a rule that does not behave as
   declared fails validation.
3. Add a benchmark fixture proving the rule fires on a realistic diff (below). `acr evolve` lists
   rules without fixtures.

Use `confidence = "high"` only when a match is almost certainly a defect; those findings are
reported as `verified`.

## Add a companion rule (diff-level)

Line rules see one added line at a time. A `[[companions]]` entry instead checks the whole diff:
it fires when a file matching `when` changed (and, if `pattern` is set, an added line in it
matches) but **no** file matching `requires` changed in the same diff. Fields: `id`, `title`,
`severity`, `confidence`, `when`, `requires`, optional `pattern`, `explanation`, `remediation`, and
`examples.flag` / `examples.pass`. Each example is a simulated diff
(`{files = [...], line = "..."}`) that validation runs. The skill's `exclude_globs` apply to
triggering files only.

`maintainability.docs` (`DOC-001`…`DOC-004`) uses these to make the reviewer flag user-facing
changes (build/CI/deploy definitions, new make targets, CLI options and env vars, schemas/APIs)
that arrive without a README, docs or CHANGELOG change; they are `major`, so the default policy blocks. Pin bumps (`uses:`, `FROM`, `image:`) and
tests do not trigger it.

## Add a skill

Create `skills/<area>/<name>/skill.toml` (`acr.skill/v1`, schema in
[schemas](../generated/schemas.md)). A skill can have rules, a prompt, or both. `tier = "small"`
or `"large"` selects the model tier for its prompt; `"none"` means rules only. Prompt text in
`prompt.md` describes *what to look for*; the engine supplies the output contract and the
prompt-injection guard. Select it in a profile via `skills = ["<id>" | "<glob>"]`.

## Add a model

Add `models/registry/<id>.toml` (`acr.model/v1`): source and runtime ref, license, context
limit, resources, capabilities, `status = "candidate"`. On a trusted runtime run
`acr models verify --pin` to record the digest. Promote to `approved` only after
`acr bench --profile balanced --gate` with the model, reviewed in a PR.
Never add weights to Git.

## Add a wrapper

See [wrappers/custom/README.md](../../wrappers/custom/README.md). Contract tests live in
`tests/contract/test_wrappers.py`.

## Benchmark fixtures (protected)

`benchmarks/fixtures/<case>/` holds `diff.patch`, `expected.json` (`path`, `line`, `rule_id`
or `category`) and `case.toml` (`description`, `expected_gate`). After adding or changing a
fixture run `python -m orchestrator bench --update-manifest`; CI rejects fixture changes that do
not update `MANIFEST.sha256`, and CODEOWNERS requires owner review for the directory.

## Local workflow

```bash
make ci             # validate, lint, tests + coverage gate, docs check, benchmark gate (toolbox container)
make shell          # shell inside the toolbox
make ci LOCAL=1     # same targets in a host .venv (after `make dev`)
make e2e            # docker: compose stack with fake runtime
make docs           # regenerate docs/generated after changing skills/models/profiles/CLI
```
