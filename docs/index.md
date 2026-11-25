# ai-code-reviewers

Free, open-source, offline code review with local language models, deterministic rules and
policy-driven quality gates. Everything runs in containers on your machine or your CI runner:
no paid APIs, no telemetry, and the code under review never leaves the machine.

```bash
git diff main... | docker run --rm -i --read-only --network none \
  munafsheikh/ai-code-reviewers:0.10.0 review --profile offline
```

| Start here | |
|---|---|
| [Getting started](usage/getting-started.md) | Step by step: pull the images, first review, add the local model, Compose, HTTP service, CI |
| [Code review examples](usage/examples.md) | Real changes and exactly what the reviewer reports |
| [Customize reviews](usage/customize.md) | Team instructions at run time, your own rules, your own image, other models |
| [Prove your code stays local](usage/privacy.md) | What enforces it and `docker compose run --rm dev prove-offline` to check it yourself |
| [CI/CD pipeline](architecture/pipeline.md) | Parallel review lanes, one gate, automatic release and deployment |

## How a review works

Deterministic rules (with self-testing examples) set a recall floor that a diff cannot talk
away; a local model adds findings, clearly marked as hypotheses; a policy decides what
blocks. If the model is unavailable the review says `degraded` and falls back to the rules.

```mermaid
flowchart LR
  diff[diff] --> rules[rules] --> merge
  diff --> router{router} -->|small / large / rules-only| model[local model] --> parse[validate vs diff] --> merge
  merge --> gate{policy gate} --> out[JSON · SARIF · Markdown]
```

## How this project ships

```mermaid
flowchart LR
  pr([pull request or push to main]) --> build
  subgraph CI["CI: every pull request and every push to main"]
    direction TB
    build["checks in the toolbox<br/>validate · lint · tests 3.13 + 3.11<br/>docs · benchmark gate"]
    cont["containers<br/>build · compose e2e<br/>deploy + rollback rehearsal"]
    scan["security<br/>secrets · SAST · deps · image scan"]
    subgraph lanes["review lanes, in parallel: rules + local model"]
      direction LR
      code["code"]
      sec["security"]
      docs["docs"]
    end
    gate{"review gate<br/>acr merge: findings · coverage · policy"}
    code --> gate
    sec --> gate
    docs --> gate
  end
  pr --> cont
  pr --> scan
  pr --> lanes
  gate -->|"PR: one comment, pass or block"| merged([merge to main])
  subgraph REL["Release: after CI is green on main"]
    direction TB
    plan["plan<br/>next version from CHANGELOG / label"]
    bump["bump · re-test · tag vX.Y.Z"]
    pub["GHCR: scan gate · SBOM · sign · GitHub release"]
    img["Docker Hub: base, then reviewer · toolbox ·<br/>fake-runtime · runtime with model baked in"]
    dep["test deployment<br/>smoke · auto-rollback"]
    site["docs site to GitHub Pages"]
    plan --> bump --> pub --> img --> dep
    plan --> site
  end
  gate -->|"main: all green"| plan
  build --> plan
  cont --> plan
  scan --> plan
```
