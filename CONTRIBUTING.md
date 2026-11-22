# Contributing

1. `docker compose run --rm dev ci` must pass (runs in the pinned toolbox image; only Docker is needed). Docker changes: also `... dev e2e` and `... dev security`. `docker compose run --rm dev help` lists every task.
2. Changes to skills, models, profiles, policies or the CLI: run `docker compose run --rm dev docs` and commit
   `docs/generated/` in the same PR (CI fails on drift).
3. New rules need `examples.match`/`examples.no_match` and a benchmark fixture
   ([extending](docs/development/extending.md)).
4. Benchmark fixtures, policies and workflows are protected (CODEOWNERS). Never weaken a gate,
   threshold or scanner to get a green build; record a time-boxed exception with reason,
   owner and expiry instead.
5. Third-party wrappers, skills and models are never auto-installed: include provenance,
   license and a security review in the PR.
6. Keep the runtime dependency-free (stdlib only). Dev tooling is pinned in `requirements-dev.txt` and baked into the `toolbox` stage of `infrastructure/docker/Dockerfile`; behind a TLS-intercepting proxy build it once with `docker build -f infrastructure/docker/Dockerfile --target toolbox -t acr-toolbox:local --build-arg HTTPS_PROXY=... --secret id=ca,src=/path/ca.crt .` (later `dev` runs reuse its cached layers). Tasks live in `infrastructure/tasks.py`: add new ones there, stdlib only.

Commit messages: imperative, scoped (`engine: ...`, `skills: ...`). One logical change per PR.

<sub>For AI coding agents: [agent guide](AGENTS.md).</sub>
