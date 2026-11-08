# Models

Weights are never stored in Git. Each model is a versioned manifest in
`registry/` (`acr.model/v1`, schema: `orchestrator/schemas/model.schema.json`)
recording identity, source, license, integrity digest, context limit, resource
needs and capabilities. The runtime (Ollama, llama.cpp, ...) downloads weights
into a Docker volume.

- `small/` — notes for small, fast models (incremental reviews, CPU).
- `large/` — notes for large models (deep reviews, GPU or high-RAM hosts).
- `benchmarks/` — per-model benchmark results produced by `acr bench`.

Lifecycle: `candidate` → (`acr models verify --pin` + benchmark pass) → `approved`
→ `deprecated` / `rejected`. Policies may require pinned digests
(`[models] require_pinned = true`); a digest mismatch at runtime disables the
model for that run and the review falls back (audited).
