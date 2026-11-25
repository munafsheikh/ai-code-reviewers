# Tiny models vs tools for hyperspecific checks

**Question.** Can very small local models (≤ 1.5B parameters) give decisive review results if
each skill asks one hyperspecific question, and the model delegates to tools where it can?

**Answer (2026-11-25).** Partly. When the question is structural, it should go to a
deterministic tool, never to the model. Those tools scored F1 1.0, while the best model ≤ 1.5B
scored 0.68, barely above the 0.667 you get by flagging everything. On semantic questions no model ≤ 1.5B was decisive, with or
without worked examples. The best was F1 0.70 against 0.667 for "flag everything", at
precision 0.61 against 0.85 for the shipped regex rules. Structural checks now ship as rules with
[analyzers](../../../orchestrator/engine/analyzers.py); semantic checks stay as rules reported
as hypotheses, and no model sits in their path.

## Method

- [`checks.toml`](checks.toml): 9 hyperspecific checks (Python, Java, Bash). Each has a
  high-recall candidate regex, one yes/no question, and a deterministic tool where the question
  is structural.
- [`cases.toml`](cases.toml): 90 labelled cases, 5 positives and 5 near-miss negatives per
  check. Every marked line matches its candidate, so each strategy answers "is this candidate
  real?". The harness refuses to run if a case breaks that.
- [`run.py`](run.py): scores the strategies below on precision, recall and F1. Stdlib only.

| Strategy | What decides |
|---|---|
| `candidate` | Flag every regex hit (the baseline: recall 1.0, precision 0.5) |
| `rule` | The rules shipped in `skills/`, including their analyzers |
| `tool` | Python `ast` (HTTP timeout, SQL formatting) or `shellcheck` (SC2086, SC2115) |
| `model:<m>` | The model answers the check's question about the marked line (JSON schema `yes`/`no`, temperature 0) |
| `hybrid:<m>` | The tool where one exists, otherwise the model |

Run on a 2-vCPU CPU host, Ollama 0.40.11.

## Results

### 1. Open review: the current model lane, on the 14 benchmark fixtures of the time

| Model | Precision | Gate accuracy | False positives | p50 latency |
|---|---|---|---|---|
| `qwen2.5-coder:0.5b` (`fast`) | 0.83 | 0.64 | 11 | 7.9 s |
| `qwen2.5-coder:1.5b` (`balanced`) | 1.00 | 1.00 | 0 | 3.7 s |

The 0.5B model adds false positives that block clean diffs, such as a *critical* "injection"
on `from svc.helpers import *`. The 1.5B model adds no false positives, but it also adds no
true positives the rules had not already found.

### 2. Candidate → verify, zero-shot (90 cases)

| Strategy | Structural F1 (30) | Semantic F1 (60) | Semantic precision | Mean latency |
|---|---|---|---|---|
| `candidate` (flag all) | 0.667 | 0.667 | 0.50 | — |
| **shipped rules** | **1.000** | 0.680 | **0.85** | ~0 |
| `tool` | **1.000** | 0.800 (1 check) | 0.80 | ~0 |
| `gemma3:270m` | 0.452 | 0.636 | 0.48 | 1.7 s |
| `smollm2:360m` | 0.000 | 0.311 | 0.47 | 0.8 s |
| `qwen2.5-coder:0.5b` | 0.000 | 0.114 | 0.40 | 2.2 s |
| `qwen3:0.6b` (think off) | 0.634 | **0.704** | 0.61 | 0.7 s |
| `qwen2.5-coder:1.5b` | 0.682 | 0.643 | 0.50 | 3.8 s |

The models fail in two ways. Some say "yes" to nearly everything (gemma3:270m, qwen2.5-coder
1.5B: recall 0.9, precision 0.5). Others say "no" to nearly everything (qwen2.5-coder 0.5B:
recall 0.07). Neither tracks the label.

### 3. Candidate → verify, few-shot (2 worked examples per answer, semantic checks only)

| Model | Semantic F1 | Precision | Recall |
|---|---|---|---|
| `gemma3:270m` | 0.419 | 0.69 | 0.30 |
| `qwen3:0.6b` | 0.378 | 1.00 | 0.23 |
| `qwen2.5-coder:1.5b` | 0.718 | 0.58 | 0.93 |

Worked examples mostly moved the models along that same yes/no axis without separating the
classes. qwen3:0.6b went from "mostly yes" to "mostly no".

## What changed in the repository because of this

- **Analyzers** (`analyzer = "…"` on a rule) confirm or reject regex candidates
  deterministically. A confirmed candidate is reported as `verified`. Shipped:
  `python.http-without-timeout` (PY-007, which now handles multi-line calls),
  `python.sql-built-string` (new INJ-006) and `shell.unquoted-expansion` (new SH-001).
- **New skill `lang.shell.core`** (SH-001…SH-006). It has no prompt: deterministic only, by design.
- **Hyperspecific Java rules:** JAVA-017 (`BigDecimal.equals`) and JAVA-018 (credential in a
  log). Both are high precision, and they report only what the line proves.
- **Found along the way:** INJ-001 misses f-strings with quoted placeholders
  (`f"… = '{name}'"`). INJ-006 covers that case and defers to INJ-001 where INJ-001 fires.

## Limits

- 90 hand-labelled cases written by the same author as the rules. A held-out set from real
  diffs would be stronger evidence.
- Single run per model at temperature 0. Larger models (≥ 3B) and logprob-thresholded answers
  were not tested; they are the next thing to try for semantic checks.
- `shellcheck` is used only in the experiment. The reviewer image does not ship it.

## Reproduce

```bash
ollama pull qwen3:0.6b   # and any other model to compare
python3 benchmarks/experiments/tiny-verify/run.py --models qwen3:0.6b,qwen2.5-coder:1.5b
python3 benchmarks/experiments/tiny-verify/run.py --models qwen3:0.6b --kind semantic --shots
python3 benchmarks/experiments/tiny-verify/run.py --models ""          # rules and tools only, no model
```

Raw results for each run, including every model reply, are in [`results/`](results/).
