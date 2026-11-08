# Examples

`sample-repo/` is a tiny Java project plus `change.patch`, a representative pull
request (SQL concatenation, swallowed exception, `==` string comparison, console output).

```bash
# Rules only, no containers, writes out/review.{json,sarif,md,txt}
make review-offline DIFF=examples/sample-repo/change.patch

# Same diff through the containerised reviewer and a local model
make up && make review DIFF=examples/sample-repo/change.patch

# Validate the JSON result against the published schema
python3 -m orchestrator.schema_check out/review.json
```

The compose stack mounts this directory read-only at `/work`, so
`docker compose run --rm reviewer review --repo /work/sample-repo --git-range HEAD~1...HEAD`
works once `sample-repo` is a git repository.
