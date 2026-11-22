# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
# One Dockerfile, layered images that share a common base:
#
#   base          python slim + non-root `acr` user + common env/labels
#   ├─ fake-runtime  deterministic Ollama stand-in for end-to-end tests
#   ├─ toolbox       + git, Docker CLI + pinned dev tooling: runs every task (docker compose run --rm dev <task>)
#   └─ reviewer      + application, pip stripped (default target; stdlib-only, read-only friendly)
#
#   runtime       CPU model runtime: Ollama binary + CPU backends + the review model(s), baked in
#                 at build time. Running it downloads nothing, so it can sit on a network with no
#                 route out. runtime-gpu: the same on the full Ollama image (CUDA/ROCm, ~4 GB more).
#
# BASE selects the parent of the derived stages. Locally it is the `base` stage below; the
# publish workflow sets it to the pushed base digest so every published image is layered
# on exactly the base it was released with.
ARG PYTHON_IMAGE=python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
ARG BASE=base
ARG OLLAMA_IMAGE=ollama/ollama:0.40.11@sha256:dea72d1e22270fe095b68fdf756d2b489d615643c5a2eaebbc5f569181e322d8
# The OS Ollama's image is built on; the CPU runtime needs nothing from it but libc/libstdc++.
ARG RUNTIME_OS_IMAGE=ubuntu:24.04@sha256:9c7f200c07e3d4a03e7249d2c16bf66a51120fb876aa2242cf31451412543289
# Docker CLI, Compose and Buildx for the toolbox: tasks that build, scan and run containers
# drive the host's Docker through its socket (docker compose run --rm dev <task>).
ARG DOCKER_CLI_IMAGE=docker:29.1.1-cli@sha256:b6b6bfc4ba4c55a1e921d6d37e4d6e11dd3d6c73e9e7e4a712371ace91e6c106
ARG COMPOSE_IMAGE=docker/compose-bin:v2.40.3@sha256:e39da8206cc48c6e2c99ce371935eef9d7eff7db600a993fd357de8b75621edf
ARG BUILDX_IMAGE=docker/buildx-bin:0.30.1@sha256:cc16bd35c1bbdde2c9d4ee08cf33be55b17e6ed2188816292dbde51064105e25

FROM ${DOCKER_CLI_IMAGE} AS docker-cli
FROM ${COMPOSE_IMAGE} AS docker-compose
FROM ${BUILDX_IMAGE} AS docker-buildx

# ---------------------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS base
ARG VERSION=0.0.0-dev
ARG REVISION=unknown
LABEL org.opencontainers.image.title="ai-code-reviewers-base" \
      org.opencontainers.image.description="Common base for ai-code-reviewers images" \
      org.opencontainers.image.source="https://github.com/munafsheikh/ai-code-reviewers" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN groupadd --system --gid 10001 acr \
 && useradd --system --uid 10001 --gid acr --home-dir /nonexistent --shell /usr/sbin/nologin acr
USER 10001:10001

# ---------------------------------------------------------------------------------------
FROM ${BASE} AS fake-runtime
LABEL org.opencontainers.image.title="ai-code-reviewers-fake-runtime" \
      org.opencontainers.image.description="Deterministic model-runtime stand-in for ai-code-reviewers end-to-end tests"
ENV FAKE_PORT=11434
COPY --chown=root:root tests/support/fake_runtime.py /opt/fake/fake_runtime.py
EXPOSE 11434
HEALTHCHECK --interval=5s --timeout=3s --retries=10 \
  CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:11434/api/tags', timeout=3)"]
ENTRYPOINT ["python", "/opt/fake/fake_runtime.py"]

# ---------------------------------------------------------------------------------------
# Developer/CI toolbox: every repository tool runs here, so the only host requirement is Docker.
FROM ${BASE} AS toolbox
LABEL org.opencontainers.image.title="ai-code-reviewers-toolbox" \
      org.opencontainers.image.description="Pinned developer and CI tooling for ai-code-reviewers"
USER root
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 \
    HOME=/tmp RUFF_CACHE_DIR=/tmp/.ruff_cache
COPY requirements-dev.txt /tmp/requirements-dev.txt
# git (tests) and curl (smoke checks); the distro snapshot is fixed by the digest-pinned base image.
# safe.directory '*': the repository is mounted at the host's own path, which varies.
# Optional corporate CA for TLS-intercepting proxies: `--secret id=ca,src=/path/ca.crt`
# (used only during the build, never stored in a layer). Proxies: `--build-arg HTTPS_PROXY=...`.
# hadolint ignore=DL3008
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi \
 && apt-get update -q \
 && apt-get install -y -q --no-install-recommends git curl \
 && rm -rf /var/lib/apt/lists/* \
 && pip install -q -r /tmp/requirements-dev.txt \
 && git config --system --add safe.directory '*'
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-compose /docker-compose /usr/local/lib/docker/cli-plugins/docker-compose
COPY --from=docker-buildx /buildx /usr/local/lib/docker/cli-plugins/docker-buildx
# Non-root by default. The `dev` Compose service runs it as root for the Docker socket and
# hands every file it creates back to the repository's owner (infrastructure/tasks.py).
USER 10001:10001
WORKDIR /src

# ---------------------------------------------------------------------------------------
# Model weights: the only stage that touches the network, and only while it is built.
# Runs on the build machine's own platform (weights are architecture-independent), so a
# multi-arch build downloads once and never runs Ollama under emulation.
FROM --platform=$BUILDPLATFORM ${OLLAMA_IMAGE} AS models
ARG MODELS="qwen2.5-coder:1.5b"
ENV OLLAMA_MODELS=/opt/ollama/models HOME=/tmp OLLAMA_NO_CLOUD=1
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN mkdir -p "$OLLAMA_MODELS/blobs" "$OLLAMA_MODELS/manifests" "$OLLAMA_MODELS/manifests-v2" \
 && if [ -n "$MODELS" ]; then \
      ollama serve >/tmp/ollama.log 2>&1 & \
      for _ in $(seq 1 60); do ollama list >/dev/null 2>&1 && break; sleep 1; done; \
      for m in $MODELS; do ollama pull "$m"; done; \
      ollama list; \
    fi \
 && chmod -R a+rX /opt/ollama

# ---------------------------------------------------------------------------------------
# Ollama's CPU backends only: the GPU libraries (CUDA, MLX, ROCm, Vulkan) are ~4 GB and are
# never loaded on CPU. The target platform's files are trimmed in a build-platform stage, so a
# multi-arch build runs nothing under emulation.
FROM ${OLLAMA_IMAGE} AS ollama-dist
FROM --platform=$BUILDPLATFORM ${OLLAMA_IMAGE} AS ollama-cpu
COPY --from=ollama-dist /usr/bin/ollama /dist/usr/bin/ollama
COPY --from=ollama-dist /usr/lib/ollama /dist/usr/lib/ollama
RUN rm -rf /dist/usr/lib/ollama/cuda_* /dist/usr/lib/ollama/mlx_cuda_* /dist/usr/lib/ollama/rocm* \
           /dist/usr/lib/ollama/vulkan /dist/usr/lib/ollama/include

# ---------------------------------------------------------------------------------------
# GPU model runtime: full Ollama image (CUDA/ROCm) plus the baked weights.
#   docker build --target runtime-gpu -t my-gpu-runtime .   then run with --gpus all
FROM ${OLLAMA_IMAGE} AS runtime-gpu
ARG MODELS="qwen2.5-coder:1.5b"
ARG VERSION=0.0.0-dev
LABEL org.opencontainers.image.title="ai-code-reviewers-runtime" \
      org.opencontainers.image.description="Local model runtime (Ollama) with the review models baked in; no downloads at run time" \
      org.opencontainers.image.source="https://github.com/munafsheikh/ai-code-reviewers" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}" \
      io.github.munafsheikh.acr.models="${MODELS}"
# Models live outside HOME so the root filesystem can be read-only at run time;
# HOME=/tmp holds Ollama's generated key on the tmpfs. NOPRUNE: never touch the baked blobs.
# NO_CLOUD: Ollama otherwise contacts ollama.com for cloud models and recommendations.
ENV OLLAMA_MODELS=/opt/ollama/models \
    OLLAMA_NOPRUNE=1 \
    OLLAMA_NO_CLOUD=1 \
    OLLAMA_HOST=0.0.0.0:11434 \
    HOME=/tmp
COPY --from=models /opt/ollama /opt/ollama
USER 10001:10001
EXPOSE 11434
HEALTHCHECK --interval=15s --timeout=10s --retries=5 CMD ["ollama", "list"]
ENTRYPOINT ["/usr/bin/ollama"]
CMD ["serve"]

# ---------------------------------------------------------------------------------------
# CPU model runtime (published as ai-code-reviewers-runtime): Ollama + CPU backends + the
# baked weights on a plain OS image. No package manager step, no CA bundle: it never connects out.
#   docker build --target runtime --build-arg MODELS="qwen2.5-coder:7b" -t my-runtime .
FROM ${RUNTIME_OS_IMAGE} AS runtime
ARG MODELS="qwen2.5-coder:1.5b"
ARG VERSION=0.0.0-dev
LABEL org.opencontainers.image.title="ai-code-reviewers-runtime" \
      org.opencontainers.image.description="Local model runtime (Ollama) with the review models baked in; no downloads at run time" \
      org.opencontainers.image.source="https://github.com/munafsheikh/ai-code-reviewers" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}" \
      io.github.munafsheikh.acr.models="${MODELS}"
# Models live outside HOME so the root filesystem can be read-only at run time;
# HOME=/tmp holds Ollama's generated key on the tmpfs. NOPRUNE: never touch the baked blobs.
# NO_CLOUD: Ollama otherwise contacts ollama.com for cloud models and recommendations.
ENV OLLAMA_MODELS=/opt/ollama/models \
    OLLAMA_NOPRUNE=1 \
    OLLAMA_NO_CLOUD=1 \
    OLLAMA_HOST=0.0.0.0:11434 \
    HOME=/tmp
COPY --from=ollama-cpu /dist/usr/ /usr/
COPY --from=models /opt/ollama /opt/ollama
USER 10001:10001
EXPOSE 11434
HEALTHCHECK --interval=15s --timeout=10s --retries=5 CMD ["ollama", "list"]
ENTRYPOINT ["/usr/bin/ollama"]
CMD ["serve"]

# ---------------------------------------------------------------------------------------
# Reviewer: stdlib-only Python, non-root, read-only friendly, no build tools at runtime.
FROM ${BASE} AS reviewer
ARG VERSION=0.0.0-dev
ARG REVISION=unknown
LABEL org.opencontainers.image.title="ai-code-reviewers" \
      org.opencontainers.image.description="Offline, model-agnostic AI code review" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"

ENV ACR_HOME=/opt/acr \
    PYTHONPATH=/opt/acr \
    ACR_CACHE_DIR=/var/cache/acr \
    ACR_BIND=0.0.0.0

USER root
# No git, compilers or package manager use at runtime: diffs arrive on stdin or over HTTP.
# pip/setuptools are not needed at runtime and carry their own CVEs (vendored urllib3, msgpack).
RUN python -m pip uninstall -y -q pip setuptools wheel 2>/dev/null; \
    rm -rf /usr/local/lib/python3.13/ensurepip \
 && mkdir -p /var/cache/acr /work \
 && chown acr:acr /var/cache/acr

WORKDIR /opt/acr
COPY --chown=root:root pyproject.toml README.md LICENSE ./
COPY --chown=root:root orchestrator/ orchestrator/
COPY --chown=root:root wrappers/ wrappers/
COPY --chown=root:root skills/ skills/
COPY --chown=root:root models/registry/ models/registry/
COPY --chown=root:root profiles/ profiles/
COPY --chown=root:root policies/ policies/
RUN python -m compileall -q orchestrator wrappers \
 && printf '#!/bin/sh\nexec python -m orchestrator "$@"\n' > /usr/local/bin/acr && chmod 0755 /usr/local/bin/acr \
 && acr validate --skip structure,fixtures

USER 10001:10001
WORKDIR /work
EXPOSE 8088
ENTRYPOINT ["python", "-m", "orchestrator"]
CMD ["--help"]
