# Model selection

The registry (`models/registry/`, catalog in [models](../generated/models.md)) covers small
CPU-friendly models through 30B-class MoE models for GPU hosts. Every manifest records
license, license class, parameter count, architecture, the runtime tag and the sources used.
Nothing here is downloaded until a runtime pulls it.

## Pick by machine

| Memory available to the model | Small tier (every diff) | Large tier (architecture, performance) | Profile |
|---|---|---|---|
| ≤ 4 GB (CI runner, Raspberry-class) | `qwen2.5-coder-0.5b`, `qwen2.5-coder-1.5b` | — | `fast`, `balanced` |
| 8 GB (laptop CPU) | `qwen2.5-coder-1.5b`, `qwen3.5-4b`, `phi4-mini-3.8b` | `qwen2.5-coder-7b` | `deep` |
| 16 GB (laptop / 12 GB GPU) | `qwen3.5-4b` | `qwen3.5-9b`, `qwen2.5-coder-14b` | `laptop` |
| 24–32 GB (workstation GPU) | `qwen2.5-coder-7b` | `qwen3-coder-30b-a3b`, `devstral-small-2-24b`, `gpt-oss-20b` | `gpu` |

`acr models recommend --ram-mb <MB> [--policy strict]` applies the same logic to the registry.
It prefers code-specialised models, then size, which is a proxy for quality and not a
measurement. Adopt a model only after it passes the benchmark gate on your fixtures.

## Families

| Family | Sizes here | License | Why include it |
|---|---|---|---|
| Qwen2.5-Coder | 0.5B, 1.5B, 7B, 14B | Apache-2.0 | Code-specialised, strong JSON compliance at small sizes; current defaults. |
| Qwen3.5 (small series, 2026) | 2B, 4B, 9B | Apache-2.0 | Recent general models with 262K context; good laptop options. |
| Qwen3-Coder | 30B-A3B (MoE) | Apache-2.0 | About 3B active parameters, so fast for its size; best code model here for a 24 GB GPU. |
| Devstral Small 2 | 24B | Apache-2.0 | Software-engineering model from Mistral; tag `devstral-small-2` (the older `devstral` tag is the 2505/2507 release). |
| gpt-oss | 20B (MoE) | Apache-2.0 | Reasoning model; slower per review, useful for logic and security defects. |
| Gemma 4 | E4B, 26B (MoE) | Apache-2.0 | Gemma 4 moved to Apache-2.0; earlier Gemma releases used custom terms. |
| Phi-4-mini | 3.8B | MIT | Compact, permissive, 128K context. |
| Granite 3.3 | 2B, 8B | Apache-2.0 | Enterprise provenance documentation. |
| Llama 3.2 | 3B | Llama 3.2 Community License | Widely deployed; custom license, so `strict` excludes it. |
| DeepSeek-Coder-V2-Lite | 16B (MoE) | DeepSeek License | Code MoE; custom license, so `strict` excludes it. |
| Codestral | 22B | Mistral Non-Production License | Evaluation only. Every gating policy excludes it; use `--policy evaluation` to benchmark. |

Base (non-instruct) completion models such as StarCoder2 base are not listed: reviews need
instruction following and structured JSON output.

## License classes and policies

| Class | Meaning | `default` | `strict` | `evaluation` |
|---|---|---|---|---|
| `permissive` | Apache-2.0 / MIT | allowed | allowed | allowed |
| `open-weight-restricted` | custom terms with use restrictions (Llama, DeepSeek) | allowed | refused | allowed |
| `non-production` | evaluation-only weights | refused | refused | allowed |

A refused model is never silently swapped: the route goes rules-only and the result says
why (`run.routing[].reason`, `degraded: true`).

## Verifying a model

1. `Model matrix` workflow (manual, monthly, and on PRs that change a manifest): pulls the
   tag on a GitHub runner (proving it exists), records the digest, runs the benchmark suite
   through the model and publishes a comparison table. Runner disk limits default runs to
   models of 6 GB or less; pass `max_disk_mb` and use a larger runner for the rest.
2. On a trusted runtime: `acr models verify --pin` records digests in the manifests.
3. Promote `status = "candidate"` to `"approved"` in a PR that links the matrix run.

Newer model families need a recent runtime; the platform pins Ollama 0.40.11.

## Other runtimes

Manifests carry a Hugging Face id (`source.hf`). With `ACR_WRAPPER=llama-cpp`, the engine
sends that id to any OpenAI-compatible server: llama.cpp `llama-server`, vLLM, LM Studio,
LocalAI. Load the corresponding weights (GGUF for llama.cpp, safetensors for vLLM) on that
server and allow its host with `ACR_ALLOWED_HOSTS`.

## Sources

Facts for newer models were checked on 2026-11-08 against these sources (also listed per
manifest under `evidence`):
[Ollama qwen3-coder:30b](https://registry.ollama.ai/library/qwen3-coder:30b),
[Qwen3-Coder-30B-A3B card](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct),
[Devstral Small 2 card](https://huggingface.co/mistralai/Devstral-Small-2-24B-Instruct-2512),
[Devstral on Ollama](https://codersera.com/blog/run-devstral-locally-with-ollama/),
[gpt-oss-20b card](https://huggingface.co/openai/gpt-oss-20b),
[gpt-oss-20b on LM Studio](https://lmstudio.ai/openai/gpt-oss-20b),
[Ollama granite3.3](https://registry.ollama.ai/library/granite3.3),
[Gemma 4 Apache-2.0](https://the-decoder.com/googles-gemma-4-is-now-available-with-apache-2-0-licensing-for-the-first-time/),
[Gemma 4 sizes on Ollama](https://dev.to/purpledoubled/how-to-run-googles-gemma-4-locally-with-ollama-all-4-model-sizes-compared-2pbh),
[Qwen3.5 small models](https://artificialanalysis.ai/articles/qwen3-5-small-models),
[Ollama phi4-mini](https://registry.ollama.ai/library/phi4-mini),
[Phi-4-mini card](https://huggingface.co/microsoft/Phi-4-mini-instruct).
Several of these are secondary sources; the model-matrix pull and each upstream license file
remain authoritative.
