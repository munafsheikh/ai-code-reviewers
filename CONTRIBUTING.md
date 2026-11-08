# Contributing

1. `make ci` must pass (runs in the pinned toolbox image; only Docker is needed). Docker changes: also `make e2e` and `make security`.
2. Changes to skills, models, profiles, policies or the CLI: run `make docs` and commit
   `docs/generated/` in the same PR (CI fails on drift).
3. New rules need `examples.match`/`examples.no_match` and a benchmark fixture
   ([extending](docs/development/extending.md)).
4. Benchmark fixtures, policies and workflows are protected (CODEOWNERS). Never weaken a gate,
   threshold or scanner to get a green build; record a time-boxed exception with reason,
   owner and expiry instead.
5. Third-party wrappers, skills and models are never auto-installed: include provenance,
   license and a security review in the PR.
6. Keep the runtime dependency-free (stdlib only). Dev tooling is pinned in `requirements-dev.txt` and baked into `infrastructure/docker/Dockerfile.toolbox`; behind a TLS-intercepting proxy build it with `make toolbox TOOLBOX_BUILD_ARGS="--build-arg HTTPS_PROXY=... --secret id=ca,src=/path/ca.crt"`.

Commit messages: imperative, scoped (`engine: ...`, `skills: ...`). One logical change per PR.
