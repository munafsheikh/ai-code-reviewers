# Examples

`sample-repo/` is a tiny Java project plus `change.patch`, a representative pull
request (SQL concatenation, swallowed exception, `==` string comparison, console output).

```bash
# Rules only, in the toolbox container, writes out/review.{json,sarif,md,txt}
./run.sh review-offline --diff examples/sample-repo/change.patch

# Same diff through the containerised reviewer and a local model
podman compose --profile model up -d --build --wait
podman compose run --rm -T reviewer review --profile balanced --format markdown < examples/sample-repo/change.patch

# Validate the JSON result against the published schema
python3 -m orchestrator.schema_check out/review.json
```

The compose stack mounts this directory read-only at `/work`, so
`podman compose run --rm reviewer review --repo /work/sample-repo --git-range HEAD~1...HEAD`
works once `sample-repo` is a git repository.
