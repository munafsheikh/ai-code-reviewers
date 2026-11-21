# Getting started

Everything runs in containers on your own machine or CI runner. The only requirement is
Docker (with Compose v2 for the full stack). No account, API key or internet connection is
needed once the images are on the machine.

## The images

| Image | What it is | Use it to |
|---|---|---|
| `munafsheikh/ai-code-reviewers:0.5.0` | The reviewer: CLI, HTTP service, rules, skills, policies | Review a diff, run the service, gate CI |
| `munafsheikh/ai-code-reviewers-runtime:0.5.0` | Ollama (CPU build) with `qwen2.5-coder:1.5b` baked in | Give the reviewer a local model; never downloads at run time |
| `munafsheikh/ai-code-reviewers-base:0.5.0` | Python slim + non-root user, shared by the others | Build your own images on the same layers |
| `munafsheikh/ai-code-reviewers-toolbox:0.5.0` | Pinned development tooling | Contribute to this project (`make` uses it) |
| `munafsheikh/ai-code-reviewers-fake-runtime:0.5.0` | Deterministic model stand-in | End-to-end tests without model weights |

All images are multi-arch (amd64, arm64) and signed. The reviewer is also published, signed
and attested, as `ghcr.io/munafsheikh/ai-code-reviewers`.

## Step 1: pull the images (the only step that needs a network)

```bash
docker pull munafsheikh/ai-code-reviewers:0.5.0
docker pull munafsheikh/ai-code-reviewers-runtime:0.5.0     # ~1.2 GB: Ollama (CPU) + model weights
```

On an air-gapped machine, pull on a connected one and move them with
`docker save munafsheikh/ai-code-reviewers:0.5.0 munafsheikh/ai-code-reviewers-runtime:0.5.0 | gzip > acr.tgz`
and `docker load < acr.tgz`.

## Step 2: your first review (rules only, seconds)

From any Git repository, review your branch against `main`:

```bash
git diff main... | docker run --rm -i --read-only --network none \
  munafsheikh/ai-code-reviewers:0.5.0 review --profile offline
```

`--network none` gives the container no network at all; the `offline` profile uses only the
deterministic rules, which need nothing else. The report is Markdown on stdout and the exit
code is the verdict:

| Exit code | Meaning |
|---|---|
| `0` | pass or warn (minor findings only) |
| `1` | blocked: fix the findings, or record a time-boxed baseline exception |
| `2` | could not review (bad input, or a strict policy with the model unavailable) |

Other outputs: `--format json,sarif,markdown,legacy --out-dir out/` writes every format at
once (SARIF uploads straight to GitHub code scanning).

## Step 3: add the local model

Start the runtime on a private network with no route out, then review through it:

```bash
docker network create --internal acr
docker run -d --name llm-runtime --network acr --read-only --tmpfs /tmp \
  munafsheikh/ai-code-reviewers-runtime:0.5.0

git diff main... | docker run --rm -i --read-only --network acr \
  -e ACR_MODEL_HOST=http://llm-runtime:11434 \
  munafsheikh/ai-code-reviewers:0.5.0 review --profile balanced
```

The report now says `Models: qwen2.5-coder:1.5b` and lists model findings as
*hypotheses* next to the rule findings. If the runtime is down the review degrades to rules
only and says so (`degraded`); use `--policy strict` to fail instead.

Profiles trade speed for depth:

| Profile | Model | Use |
|---|---|---|
| `offline` | none | fastest; deterministic rules only |
| `fast` | 0.5B, one call | pre-commit |
| `balanced` | 1.5B | default for pull requests |
| `deep`, `laptop`, `gpu` | 4B to 14B | scheduled or release reviews |
| `legacy` | as configured | Firefly `ReviewGate.java` compatibility |

Larger models need a runtime with them baked in: see [Customize reviews](customize.md#use-a-different-model).

## Step 4 (optional): the stack with Compose

[`examples/compose/compose.yaml`](https://github.com/munafsheikh/ai-code-reviewers/blob/main/examples/compose/compose.yaml)
runs the same two containers from the published images, both on an internal network, with
team instructions mapped in from `./instructions.d`:

```bash
curl -sSLO https://raw.githubusercontent.com/munafsheikh/ai-code-reviewers/main/examples/compose/compose.yaml
mkdir -p instructions.d
docker compose up -d --wait
git diff main... | docker compose run --rm -T reviewer review
docker compose down
```

With a checkout of this repository, `make up` builds and starts the same stack from source
(including the runtime, so the model is downloaded once, at build time).

## Step 5 (optional): the HTTP service

Publishing a port needs a normal network, so the service gets two: a bridge network for the
port (bound to `127.0.0.1` only) and the internal `acr` network to reach the runtime. The
runtime itself stays on the internal network only.

```bash
docker network create acr-edge
docker run -d --name acr --network acr-edge -p 127.0.0.1:8088:8088 --read-only --tmpfs /tmp \
  -e ACR_MODEL_HOST=http://llm-runtime:11434 \
  munafsheikh/ai-code-reviewers:0.5.0 serve
docker network connect acr acr
curl -s --data-binary @change.patch http://127.0.0.1:8088/v1/review        # JSON result
curl -s http://127.0.0.1:8088/readyz                                       # ready (model reachable)?
```

Endpoints: `POST /v1/review` (size- and concurrency-limited), `/healthz`, `/readyz`,
`/metrics`. Even on the bridge network the reviewer only ever contacts allow-listed hosts
(see [Prove your code stays local](privacy.md)).

## Step 6: gate pull requests in CI

GitHub Actions: the composite action reviews the PR diff, comments, uploads SARIF and fails
the job when the gate blocks.

```yaml
permissions: {contents: read, pull-requests: write, security-events: write}
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with: {fetch-depth: 0}
      - uses: munafsheikh/ai-code-reviewers/integrations/github@v0.5.0
        with:
          profile: balanced          # runtime defaults to the image with the model baked in
          require-model: 'true'      # fail instead of silently falling back to rules
```

To split the review into parallel lanes (as this project does for its own PRs), run the
action once per lane with `skills:`, then merge with `merge-results:`; see
[the pipeline](../architecture/pipeline.md). GitLab, Azure DevOps and Firefly templates are in
[`integrations/`](https://github.com/munafsheikh/ai-code-reviewers/tree/main/integrations).

## Step 7 (optional): review issues before work starts

```bash
gh issue view 42 --json number,title,body,labels,url | \
  docker run --rm -i --read-only --network none munafsheikh/ai-code-reviewers:0.5.0 review --issue - --profile offline
```

Issues are checked against a Definition of Ready (acceptance criteria, reproducible bug
reports, no placeholder text, no screenshot-only descriptions).

## Next

- [Code review examples](examples.md): real changes and what the reviewer reports.
- [Customize reviews](customize.md): team instructions, your own rules, your own image.
- [Prove your code stays local](privacy.md): how to verify nothing leaves the machine.
