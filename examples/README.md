# Examples

`sample-repo/` is a tiny Java project plus `change.patch`, a representative pull
request (SQL concatenation, swallowed exception, `==` string comparison, console output).

```bash
# Rules only (in the toolbox), writes out/review.{json,sarif,md,txt}
docker compose run --rm dev review-offline --diff examples/sample-repo/change.patch

# Same diff through the containerised reviewer and a local model
docker compose --profile model up -d --build --wait
docker compose run --rm -T reviewer review < examples/sample-repo/change.patch

# Validate the JSON result against the published schema
docker compose run --rm dev schema-check out/review.json
```

The compose stack mounts this directory read-only at `/work`, so
`docker compose run --rm reviewer review --repo /work/sample-repo --git-range HEAD~1...HEAD`
works once `sample-repo` is a git repository.
