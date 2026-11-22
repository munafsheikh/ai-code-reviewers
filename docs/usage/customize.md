# Customize reviews

Four levers, from lightest to heaviest. None needs a fork of this project.

| You want to | Use | Affects |
|---|---|---|
| Tell the model what your team cares about | [Team instructions](#team-instructions-at-run-time) | model review |
| Enforce a rule deterministically | [Your own skills](#your-own-rules-and-skills) | rules (and optionally the model) |
| Ship both to every developer and CI job | [Your own image](#your-own-image) or [Compose mounts](#compose-map-them-in) | everything |
| Use a bigger or different model | [A runtime with that model baked in](#use-a-different-model) | model review |
| See only findings you trust enough | [A minimum confidence](#confidence-levels) | what is reported and gated |

## Team instructions at run time

Instructions are plain Markdown the model receives with every review: conventions to enforce,
what to be strict or lenient about, context about the codebase. They are read at run time
from three places, all optional and combined in this order:

1. every `*.md` / `*.txt` in `/etc/acr/instructions.d` (or `$ACR_INSTRUCTIONS_DIR`), sorted by
   name (so `10-security.md` comes before `20-style.md`); `README*` files are ignored;
2. `--instructions FILE` on `acr review` (repeatable): e.g. per-repository or per-PR context;
3. `$ACR_INSTRUCTIONS`: inline text, handy in CI.

```markdown
<!-- instructions.d/10-team.md -->
- Money is always `Decimal` or integer cents; flag any float arithmetic on amounts.
- Every new HTTP handler must check authorization before reading the request body.
- Be strict about missing tests in `billing/`; be lenient about style.
```

```bash
git diff main... | docker run --rm -i --read-only --network acr \
  -v "$PWD/instructions.d:/etc/acr/instructions.d:ro" \
  -e ACR_MODEL_HOST=http://llm-runtime:11434 \
  munafsheikh/ai-code-reviewers:0.7.0 review --profile balanced

# or one file for this run, or inline:
... review --instructions .github/review-instructions.md
... -e ACR_INSTRUCTIONS="This PR is a hotfix: only report correctness and security issues." ...
```

How they are handled:

- **Trusted, separately from the diff.** Instructions go into the system prompt; the diff is
  fenced as untrusted data. Text in the diff cannot pose as an instruction, and instructions
  cannot override the security rules or the output format.
- **Model only.** Deterministic rules are unaffected; a rule finding cannot be talked away by
  instructions any more than by the diff. To *enforce* a convention, write a rule (below).
- **Traceable.** Each review records every source by name, size and SHA-256 in
  `run.instructions` and prints it in the report (`Team instructions: 10-team.md (3f1c2a9b)`),
  so a result can be tied to the exact guidance it used. Content is never stored.
- **Bounded** to 8,000 characters in total, so instructions cannot crowd out the diff.

## Your own rules and skills

A skill is a directory with a `skill.toml`: deterministic rules (regular expressions with
built-in examples that `acr validate` executes), optionally a `prompt.md` for the model, and
the files and languages it applies to. Put yours in `/etc/acr/skills.d` (or any directory in
`$ACR_SKILLS_DIRS`); they load next to the built-in ones.

```toml
# skills.d/team-money/skill.toml
id = "team.money"
version = "1.0.0"
interface = "acr.skill/v1"
category = "code-quality"
description = "Team rule: money must never be a float."
languages = ["python", "java", "javascript", "typescript"]
file_globs = ["*"]
tier = "none"

[[rules]]
id = "MON-001"
title = "Float used for a money amount"
severity = "major"
confidence = "medium"
pattern = '''(?i)\b(?:float|parseFloat|Number)\s*\(\s*\w*(?:amount|price|total|balance)\w*'''
explanation = "Binary floating point cannot represent most decimal amounts exactly."
remediation = "Use Decimal (Python), BigDecimal (Java) or integer cents."
examples.match = ["total = float(amount)", "const p = parseFloat(priceText)"]
examples.no_match = ["total = Decimal(amount)", "ratio = float(count)"]
```

A `major` rule finding blocks under the default policy. Skill ids must be unique; to drop a
built-in skill, select skills explicitly with `--skills` / `$ACR_SKILLS` (globs, e.g.
`"security.*,team.*"`). The full manifest format, companion (diff-level) rules and categories
are in [Extending](../development/extending.md).

## Your own image

Bake instructions and skills into an image built on the published reviewer, so every
developer and pipeline runs exactly the same review. This is
[`examples/custom-image`](https://github.com/munafsheikh/ai-code-reviewers/tree/main/examples/custom-image):

```dockerfile
ARG REVIEWER_IMAGE=munafsheikh/ai-code-reviewers:0.7.0
FROM ${REVIEWER_IMAGE}
COPY instructions.d/ /etc/acr/instructions.d/
COPY skills.d/ /etc/acr/skills.d/
RUN acr validate --skip structure,fixtures     # fail the build if a rule's examples misbehave
```

```bash
docker build -t my-org/code-reviewer examples/custom-image
printf -- '--- a/billing/pay.py\n+++ b/billing/pay.py\n@@ -0,0 +1 @@\n+total = float(amount) * 1.2\n' \
  | docker run --rm -i --read-only --network none my-org/code-reviewer review --profile offline
# BLOCK: MON-001 Float used for a money amount (billing/pay.py:1)
```

Point CI at it with the action's `image:` input. The image adds no network access and no
dependencies; it is the same reviewer with two more directories.

Build on `munafsheikh/ai-code-reviewers` (the reviewer) for this. `ai-code-reviewers-base` is
the Python layer the reviewer and toolbox share; use it only to build a different tool on the
same layers.

## Compose: map them in

To change instructions without rebuilding, mount them. The repository's `compose.yaml` maps
`./config/instructions.d` and `./config/skills.d` (override with `ACR_INSTRUCTIONS_PATH` and
`ACR_SKILLS_PATH`); [`examples/compose/compose.yaml`](https://github.com/munafsheikh/ai-code-reviewers/blob/main/examples/compose/compose.yaml)
does the same from the published images:

```yaml
services:
  reviewer:
    image: munafsheikh/ai-code-reviewers:0.7.0
    volumes:
      - ./instructions.d:/etc/acr/instructions.d:ro
      - ./skills.d:/etc/acr/skills.d:ro
```

Edit a file and the next review uses it; nothing restarts.

## Use a different model

The runtime image carries its model, so changing models means using a runtime built with
it. Build once, on a connected machine:

```bash
docker build -f infrastructure/docker/Dockerfile --target runtime \
  --build-arg MODELS="qwen2.5-coder:7b" -t my-org/acr-runtime:7b .
# GPU hosts: --target runtime-gpu (full Ollama image with CUDA/ROCm), run with --gpus all
```

then review with the matching profile or model:

```bash
... review --model qwen2.5-coder:7b          # 7B for every model-backed skill
... review --profile deep                   # 1.5B for focused skills, 7B for architecture and performance:
                                            # needs a runtime built with MODELS="qwen2.5-coder:1.5b qwen2.5-coder:7b"
```

`acr models recommend --ram-mb 16000` suggests models for a memory budget;
[Model selection](../operations/model-selection.md) compares them. Several models can share
one runtime: `--build-arg MODELS="qwen2.5-coder:1.5b qwen2.5-coder:7b"`.

## Confidence levels

Every finding has a confidence, `low` < `medium` < `high`, saying how likely it is to be a
real defect:

| Source | Confidence | Reported as |
|---|---|---|
| Rule declared `confidence = "high"` (a precise pattern; its examples run on every build) | `high` | *verified* |
| Rule declared `medium` or `low` (a pattern that also matches harmless code) | as declared | *hypothesis* |
| Model, confidence given | as given by the model | *hypothesis* |
| Model, no confidence given | `medium` | *hypothesis* |
| Model, cited line is not one the diff changed | forced to `low` | *hypothesis* |

Model findings are always hypotheses: the pipeline checks they point at real changed code, but
not that the model's reasoning is right.

**Minimum confidence.** Findings below the minimum are left out of the report and cannot
block. The minimum in force is the first of:

1. `--min-confidence low|medium|high` on `acr review` / `acr merge` (GitHub action:
   `min-confidence:`);
2. `$ACR_MIN_CONFIDENCE`;
3. the policy's `[gate] min_confidence`;
4. the built-in default, `low`.

Every shipped policy sets `min_confidence = "low"`, so by default every finding is reported and
can block. Raise it per run when you want less noise:

```bash
git diff main... | docker run --rm -i --read-only --network none \
  munafsheikh/ai-code-reviewers:0.7.0 review --profile offline --min-confidence high
# Minimum confidence: high (from --min-confidence); hidden below it: 1 critical, 1 major
```

Nothing is hidden silently: the report prints that line, and `run.confidence` in the JSON
records the minimum, where it came from and how many findings of each severity it hid. Be
deliberate with `high`: several security rules are `medium` (they match some safe code too),
so a high minimum hides them.

A separate setting, `[gate] model_min_confidence_to_block` (`medium` in `default`, `low` in
`strict`), decides which *model* findings may block among those reported; rule findings at or
above the minimum always can.

## Policies

What blocks is a policy decision, separate from what is found: `default` blocks on `major`,
`strict` also fails when the model is unavailable, and baselined findings (with an owner and
an expiry date) never block. See [Profiles & policies](../generated/profiles.md).
