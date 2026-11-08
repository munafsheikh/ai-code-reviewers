# Firefly integration

Firefly's original gate (`tools/review-gate/ReviewGate.java` + `.github/workflows/review-gate.yml`)
is the reference implementation this platform was extracted from. Firefly now consumes the
platform instead of carrying its own copy.

| Firefly before | Platform equivalent |
|---|---|
| `ReviewGate.java` prompt | skill `lang.java.first-pass-gate` (byte-identical, sha256-tested) |
| `SEVERITY: NONE\|MINOR\|BLOCK` parsing, fail-open | `legacy` profile / `--format legacy` (golden-tested, 11 cases) |
| exit 0 / 1 (BLOCK) / 2 (no model, runtime down) | same codes |
| `LLM_HOST`, `LLM_MODEL` | still honoured (aliases of `ACR_MODEL_HOST`, `ACR_SMALL_MODEL`) |
| Ollama service container + model pull + PR comment + enforce | `integrations/github` action |
| 24,000-char truncation | `legacy`: identical; other profiles: whole-file chunks, skipped files reported |

## Modes

- **Structured (default in the drop-in workflow):** `balanced` profile over `*.java` — Java,
  security and quality rules plus the model; SARIF and Markdown; degrades to rules-only when the
  runtime variable is not set, so the job is useful immediately.
- **Legacy:** `profile: legacy` reproduces the original text protocol exactly (requires `LLM_MODEL`).

## Files

- [`review-gate.yml`](review-gate.yml) — drop-in replacement for Firefly's workflow.
- [`review-gate.sh`](review-gate.sh) — local/pre-commit wrapper (`git diff --cached | tools/review-gate/review-gate.sh`).

Repository variables (unchanged): `LLM_RUNTIME_IMAGE` (model runtime image; empty = rules only),
`LLM_MODEL` (runtime ref, e.g. `qwen2.5-coder:1.5b`).
