# Prove your code stays local

The claim: **code under review never leaves the machine that reviews it.** This page lists
what enforces that, and how to check each part yourself instead of trusting it.

## One command

From a checkout of this repository:

```bash
make build runtime            # reviewer image + runtime with the model baked in (downloads once, here)
make prove-offline            # or: make prove-offline IMAGE=munafsheikh/ai-code-reviewers:0.8.0 RUNTIME_IMAGE=munafsheikh/ai-code-reviewers-runtime:0.8.0
```

[`prove-offline.sh`](https://github.com/munafsheikh/ai-code-reviewers/blob/main/infrastructure/scripts/prove-offline.sh)
creates a Docker network with `--internal` (no gateway: the kernel has no route out of it),
puts the model runtime on it, then:

1. checks the network really is internal and the runtime is attached to nothing else;
2. tries, **from inside both containers**, to open TCP connections to `1.1.1.1:443` and
   `8.8.8.8:53` and to resolve `github.com` and `ollama.com`; every attempt must fail;
3. reviews a diff **with the model** on that network and requires a non-degraded result;
4. reviews again, rules only, with `--network none` (no network interface at all).

```text
1. Isolated network
  PASS  network acr-proof-10481 is internal (no gateway, no route to the internet)
  PASS  runtime is attached to acr-proof-10481 only
2. No way out (probes from inside the containers)
  PASS  reviewer container: TCP to 1.1.1.1:443 and 8.8.8.8:53 refused, DNS for github.com and ollama.com fails
  PASS  runtime container: TCP to 1.1.1.1:443 refused
3. The review still works, with the model, inside the isolated network
  PASS  reviewed 1 file(s) with model qwen2.5-coder:1.5b (1 call(s)), gate: block
4. Rules-only review with no network interface at all (--network none)
  PASS  offline review completed with --network none
RESULT: PASS - the code under review could not leave this machine.
```

If the review can run with no route to the internet, it did not need one, and the network
layer guarantees it could not have used one.

## What enforces it (defense in depth)

| Layer | Mechanism | Check it |
|---|---|---|
| Network | Reviewer and runtime on a Docker `--internal` network (Compose: `backend`, `internal: true`) | `docker network inspect <net> -f '{{.Internal}}'` prints `true` |
| No model download | The runtime image has the weights baked in at build time (`OLLAMA_MODELS=/opt/ollama/models`); nothing pulls at run time | `docker run -d --name rt --network none <runtime>` then `docker exec rt ollama list` lists the model with no network at all |
| No phone-home in the runtime | `OLLAMA_NO_CLOUD=1`: Ollama otherwise contacts `ollama.com` for cloud models and recommendations | `docker logs <runtime>` shows no outbound attempts; on an internal network any would fail |
| Egress allowlist in the reviewer | Wrappers may only contact loopback, `llm-runtime`/`fake-runtime` or hosts you add to `ACR_ALLOWED_HOSTS`; anything else raises before a socket opens | [`orchestrator/engine/http.py`](https://github.com/munafsheikh/ai-code-reviewers/blob/main/orchestrator/engine/http.py) |
| Proxy bypass | `HTTP(S)_PROXY` is ignored unless `ACR_ALLOW_PROXY=1`, so a corporate proxy cannot silently forward the diff | same file, `_opener()` |
| No third-party runtime code | The reviewer is stdlib-only Python with pip removed from the image; no SDKs, no telemetry libraries | `docker run --rm --entrypoint python <reviewer> -m pip` fails; the SBOM lists only the OS and Python |
| Declared permissions | Every wrapper declares `network = "none" \| "allowlist"`; `acr validate` checks the code matches | `wrappers/*/wrapper.toml` |
| Read-only, unprivileged | Containers run read-only, as uid 10001, with all capabilities dropped | `docker inspect` (`ReadonlyRootfs`, `User`, `CapDrop`) |

## Check it by hand

**Rules only, no network interface at all.** This is the strongest form: the container has
only a loopback device.

```bash
git diff main... | docker run --rm -i --read-only --network none munafsheikh/ai-code-reviewers:0.8.0 review --profile offline
```

**With the model, on an internal network.** Step 3 of [Getting started](getting-started.md#step-3-add-the-local-model)
already runs this way. To watch the traffic, capture on the network's bridge while a review
runs; only connections between the two containers appear:

```bash
br=br-$(docker network inspect acr -f '{{.Id}}' | cut -c1-12)
sudo tcpdump -ni "$br" 'not (net 172.16.0.0/12 or net 10.0.0.0/8 or net 192.168.0.0/16)'   # stays silent
```

**On the result.** Every review records what it used: `run.models` (id, ref, digest),
`run.calls` (count of model calls), `run.routing`, `run.instructions` (names and hashes) and
`run.infrastructure_errors`. A review that could not reach its runtime says `degraded`; there
is no hidden fallback to a hosted model because no code path for one exists.

## The one network step: getting the images

Pulling images, and building the runtime (which downloads the model), are the only steps
that use the network, and they handle no code. On an air-gapped machine, pull or build on a
connected one, then `docker save` / `docker load` (see
[Getting started](getting-started.md#step-1-pull-the-images-the-only-step-that-needs-a-network)).
Verify what you loaded with cosign: `cosign verify ghcr.io/munafsheikh/ai-code-reviewers@<digest> --certificate-identity-regexp '^https://github.com/munafsheikh/ai-code-reviewers/' --certificate-oidc-issuer https://token.actions.githubusercontent.com`.

## What is not covered

- **CI runners you do not own.** On GitHub-hosted runners the code is already on GitHub's
  machine; the reviewer adds no further destination, but the runner is not your machine.
  Use self-hosted runners for that guarantee.
- **Operator configuration.** Adding a remote host to `ACR_ALLOWED_HOSTS`, setting
  `ACR_ALLOW_PROXY=1`, or attaching the containers to a non-internal network are deliberate
  choices that widen the boundary; `prove-offline` fails if the runtime is on any other network.
- **The HTTP service.** Publishing its port needs a non-internal network for the reviewer
  container; the egress allowlist still applies, and the runtime stays internal.
