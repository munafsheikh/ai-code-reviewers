# GitHub Actions adapter

Composite action at `integrations/github/action.yml`. Reference a release tag (`@v0.2.0`), or pin the
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
        uses: munafsheikh/ai-code-reviewers/integrations/github@v0.2.0
        with:
          profile: balanced          # offline = rules only, no model download
          paths: "*.java *.py"
      - uses: github/codeql-action/upload-sarif@33d7b85da1a04171e211befe2c739303b9a4c066 # v4.39.3
        if: always()
        with: {sarif_file: acr-review/review.sarif, category: ai-code-review}
```

Outputs: `gate` (`pass|warn|block|error`), `exit-code`, `sarif`. With `enforce: true`
(default) the job fails on `block` (exit 1) and on `error` (exit 2, strict policies only).
The default `balanced` policy degrades to rules-only when the model is unavailable and
says so in the report.
