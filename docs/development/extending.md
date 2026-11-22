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

`documentation.sync` (`DOC-001`…`DOC-004`) uses these to block user-facing changes (build/CI/deploy
definitions, new make targets, CLI options and env vars, schemas/APIs) that arrive without a
README, docs or CHANGELOG change. Pin bumps (`uses:`, `FROM`, `image:`) and tests do not trigger it.

## Add an expectation (document-level)

Line rules find what is present. An `[[expects]]` entry finds what is missing: it reads each
matching file as one document and fires when `pattern` is **not** found. Optional `when` limits it
to documents that match (e.g. issues labelled `bug`); `unless` exempts documents. Fields: `id`,
`title`, `severity`, `confidence`, `pattern`, optional `when` / `unless`, `explanation`,
`remediation`, and `examples.flag` / `examples.pass` (whole documents, run by validation). The
finding is reported at the document's first line.

## Lifecycle artifacts

Work items other than code are reviewed as one added file at a virtual path starting with `@`.
`acr review --issue` renders a GitHub issue as `@issue/<number>`: a `# title` line, `Labels:`
and `Issue:` lines, a blank line, then the body. Rules, expectations and model prompts see that
text; findings link to the issue and carry `location.anchor`, the nearest heading.

Artifacts are opt-in: a skill reaches them only through a `file_globs` entry starting with `@`
(`refinement.issue` uses `@issue/*`), so code skills with `*` never review an issue. Coverage
reports them as kind `artifact`, and each needs a check from its stage's category
(`refinement` for issues).

## Categories and coverage

Every skill has one `category`. Code categories: `security`, `code-quality`, `architecture`,
`performance`, `maintainability`, `testing`. Documentation category: `documentation`:
`documentation.sync` (code changed, docs did not) and `documentation.content` (defects inside docs:
placeholders `DOC-101`, conflict markers `DOC-102`, machine-local paths `DOC-103`, insecure links
`DOC-104`; plus a model prompt for docs that contradict the code).

Each review records `run.coverage`: for every changed file, which categories actually examined it
(a rule or companion applies, or its prompt reached an available model). Files matching
`*.md`, `*.rst`, `*.adoc`, `docs/*` need a `documentation` check; every other file needs a code
check. With `[gate] require_coverage = true` (`default`, `strict`) an uncovered file blocks the
review, so a profile that drops a category, or a file type no skill understands, cannot pass
silently. A new skill should therefore cover a file type or category the existing ones miss.

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
docker compose run --rm dev ci      # validate, lint, tests + coverage gate, docs check, benchmark gate
docker compose run --rm dev shell   # shell inside the toolbox
docker compose run --rm dev e2e     # compose stack with fake runtime
docker compose run --rm dev docs    # regenerate docs/generated after changing skills/models/profiles/CLI
```

<sub>For AI coding agents: [agent guide](../../AGENTS.md).</sub>
