# Contributing

1. `make dev` then `make ci` must pass. Docker changes: also `make e2e` and `make security`.
2. Changes to skills, models, profiles, policies or the CLI: run `make docs` and commit
   `docs/generated/` in the same PR (CI fails on drift).
3. New rules need `examples.match`/`examples.no_match` and a benchmark fixture
   ([extending](docs/development/extending.md)).
4. Benchmark fixtures, policies and workflows are protected (CODEOWNERS). Never weaken a gate,
   threshold or scanner to get a green build; record a time-boxed exception with reason,
   owner and expiry instead.
5. Third-party wrappers, skills and models are never auto-installed: include provenance,
   license and a security review in the PR.
6. Keep the runtime dependency-free (stdlib only). Dev tooling is pinned in `requirements-dev.txt`.

Commit messages: imperative, scoped (`engine: ...`, `skills: ...`). One logical change per PR.
