# Architecture

## Components

```mermaid
flowchart LR
  subgraph Inputs
    D[unified diff<br/>stdin / file / git range / HTTP]
  end
  subgraph Engine[orchestrator]
    P[diff parser] --> R[rules engine<br/>skills/*/skill.toml]
    P --> RT[router<br/>profiles + model registry]
    RT --> W[wrapper adapter<br/>acr.wrapper/v1]
    W --> REC[recovery<br/>retry · circuit · cache · deadline]
    R --> M[merge + dedupe]
    REC --> PA[output parser<br/>validates against diff]
    PA --> M
    M --> G[gate<br/>policy + baseline]
  end
  subgraph Runtime[model runtime, local]
    O[Ollama / llama.cpp / CLI]
  end
  W <-->|loopback / compose network only| O
  G --> J[JSON acr.result/v1]
  G --> S[SARIF 2.1.0]
  G --> MD[Markdown]
  G --> L[legacy SEVERITY text]
  D --> P
```

| Layer | Path | Contract |
|---|---|---|
| Models | `models/registry/*.toml` | `acr.model/v1` — identity, source, license, digest, context, resources |
| Skills | `skills/**/skill.toml` (+ `prompt.md`) | `acr.skill/v1` — deterministic rules with self-test examples, optional model prompt and tier |
| Wrappers | `wrappers/*/wrapper.toml` (+ `adapter.py`) | `acr.wrapper/v1` — `health()`, `generate()`; declared permissions statically enforced |
| Profiles | `profiles/*/profile.toml` | routing, budgets, retry, circuit, cache, generation settings |
| Policies | `policies/review/*.toml` | gate thresholds, model trust, infrastructure-failure behaviour, baseline |
| Results | `orchestrator/schemas/review-result.schema.json` | `acr.result/v1` |

Reference tables generated from these sources: [skills](../generated/skills.md),
[models](../generated/models.md), [profiles and policies](../generated/profiles.md),
[schemas](../generated/schemas.md), [CLI](../generated/cli.md), [environment](../generated/configuration.md).

## Review flow

```mermaid
sequenceDiagram
  participant C as Caller (CLI / CI / HTTP)
  participant E as Engine
  participant Ru as Rules
  participant Ro as Router
  participant W as Wrapper
  participant Rt as Runtime
  C->>E: diff + profile
  E->>Ru: added lines
  Ru-->>E: rule findings (verified / hypothesis)
  E->>Ro: skills with prompts
  Ro-->>E: routes (tier -> model | rules-only + reason)
  E->>W: health (bounded retry, circuit breaker)
  alt runtime healthy and model digest OK
    loop chunks within budget and deadline
      E->>W: generate (cache first)
      W->>Rt: HTTP / subprocess
      Rt-->>W: completion
      W-->>E: text
      E->>E: parse, discard hallucinated paths, mark unverified lines
    end
  else unavailable
    E->>E: audit fallback_rules_only, degraded = true
  end
  E->>E: merge (model corroborates rules), baseline, gate
  E-->>C: result + exit code (0 pass/warn, 1 block, 2 error)
```

## Design decisions

| Decision | Rationale |
|---|---|
| Python stdlib-only runtime | No third-party runtime dependencies → minimal supply-chain surface; image is ~178 MB with pip removed. |
| Rules + models, never models alone | Rules give a deterministic recall floor and cannot be talked out of a finding by prompt injection; models add hypotheses. |
| Model findings are always `hypothesis` | Probabilistic output is labelled as such; only high-confidence rule matches are `verified`. |
| Findings must cite a file in the diff | Hallucinated paths are discarded; out-of-hunk lines are kept at `low` confidence with `location.verified = false`. |
| Degrade, don't fail, by default | An unavailable model must not block delivery; the `strict` policy opts into failing (exit 2). Degradation is always reported. |
| TOML manifests + JSON Schema | Human-editable, comment-friendly, parsed by `tomllib`; schemas are published and cross-checked with `jsonschema` in tests. |
| Legacy profile | Byte-identical prompt and wire payload, same stdout and exit codes as Firefly's `ReviewGate.java` (regression-tested). |
| Wrappers loaded from manifests | Hyphenated directories (`llama-cpp`), drop-in custom wrappers, and static permission checks before load. |

## Deployment topology

```mermaid
flowchart TB
  subgraph host[Docker host]
    subgraph edge[network: edge]
      direction LR
    end
    subgraph backend[network: backend, internal]
      reviewer[reviewer<br/>uid 10001 · read-only · cap_drop ALL<br/>127.0.0.1:8088]
      runtime[llm-runtime<br/>Ollama · volume llm-models]
      init[model-init<br/>one-shot pull, bounded retries]
      fake[fake-runtime<br/>profile: test]
    end
  end
  reviewer --- runtime
  init --> runtime
  runtime -. model downloads only .- edge
  reviewer -. published port .- edge
```

The `backend` network is `internal: true`. Wrapper egress is additionally restricted in
code to loopback, compose service names and `ACR_ALLOWED_HOSTS`, with proxies bypassed.
