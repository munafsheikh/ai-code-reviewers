# Custom wrappers

A wrapper adapts one inference runtime to the `acr.wrapper/v1` contract
(`orchestrator/contracts.py::ModelAdapter`). To add one:

1. Create `wrappers/<id>/wrapper.toml` (see `example-echo/`) declaring `id`,
   `interface = "acr.wrapper/v1"`, `entrypoint = "<file>.py:<Class>"` and
   `[permissions]` (`network`, `subprocess`, `filesystem`).
2. Implement `health()` and `generate(GenerationRequest) -> Completion`. Raise
   `AdapterError(transient=True)` for retryable failures only.
3. Use `orchestrator.engine.http.request_json` for HTTP so the egress allowlist applies.
4. Run `acr validate` — it statically checks that the code only uses capabilities
   its manifest declares (e.g. no `subprocess` import without `subprocess = true`).
5. Add a contract test in `tests/contract/`.

Third-party wrappers are never auto-installed. Review provenance, license and
code before adding one; they execute inside the reviewer container.
