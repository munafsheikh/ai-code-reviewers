# GitHub Actions adapter

Composite action at `integrations/github/action.yml`. Reference a release tag (`@v0.7.0`), or pin the
tag's commit SHA with the tag as a comment, as this repository's own workflows do.

```yaml
permissions: {contents: read, pull-requests: write, security-events: write}
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with: {fetch-depth: 0}
      - id: acr
        uses: munafsheikh/ai-code-reviewers/integrations/github@v0.7.0
        with:
          profile: balanced          # offline = rules only, no model download
          paths: "*.java *.py"
      - uses: github/codeql-action/upload-sarif@33d7b85da1a04171e211befe2c739303b9a4c066 # v4.39.3
        if: always()
        with: {sarif_file: acr-review/review.sarif, category: ai-code-review}
```

Reviews and links use the PR's head commit (not GitHub's temporary merge commit), so line
permalinks in the comment stay valid after the PR closes. Set `head-ref: HEAD` to review local
commits made earlier in the job (as Firefly's end-to-end test does).

Outputs: `gate` (`pass|warn|block|error`), `exit-code`, `degraded`, `sarif`. With
`enforce: true` (default) the job fails on `block` (exit 1) and on `error` (exit 2, strict
policies only).

The model runtime defaults to `munafsheikh/ai-code-reviewers-runtime` of the same release,
which has `qwen2.5-coder:1.5b` baked in, so no model is downloaded during the job. A stock
Ollama image also works (`runtime-image:`); the models in `pull-models` are then pulled.
When the model is unavailable the review degrades to rules only and says so in the report;
set `require-model: true` to fail the job instead.

**Parallel lanes.** Run the action once per lane with `skills:` (e.g. `"security.*"`),
`comment: 'false'`, `enforce: 'false'` and a distinct `artifact-name`, then once more with
`merge-results:` listing the lanes' `review.json` files (and `lane-names:`): the merge
de-duplicates findings, judges coverage across lanes, comments once and enforces one gate.
This repository's own CI does exactly that (`review` and `review-gate` jobs in
`.github/workflows/ci.yml`). On push events pass `base-ref: ${{ github.event.before }}` to
review the pushed commits.

**Team instructions.** `instructions: .github/review-instructions.md` gives the model your
team's guidance (files are mounted read-only; several can be listed), and `ACR_INSTRUCTIONS`
in the job's environment is forwarded too. To ship instructions and your own rules to every
repository, pass `image:` a reviewer image with them baked in (see `examples/custom-image`).
