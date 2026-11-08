# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
# One Dockerfile, layered images that share a common base:
#
#   base          python slim + non-root `acr` user + common env/labels
#   ├─ fake-runtime  deterministic Ollama stand-in for end-to-end tests
#   ├─ toolbox       + git + pinned dev tooling (validate, lint, tests, docs, benchmarks)
#   └─ reviewer      + application, pip stripped (default target; stdlib-only, read-only friendly)
#
# BASE selects the parent of the derived stages. Locally it is the `base` stage below; the
# publish workflow sets it to the pushed base digest so every published image is layered
# on exactly the base it was released with.
ARG PYTHON_IMAGE=python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
ARG BASE=base

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
# git is needed by tests; the distro snapshot is fixed by the digest-pinned base image.
# Optional corporate CA for TLS-intercepting proxies: `--secret id=ca,src=/path/ca.crt`
# (used only during the build, never stored in a layer). Proxies: `--build-arg HTTPS_PROXY=...`.
# hadolint ignore=DL3008
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi \
 && apt-get update -q \
 && apt-get install -y -q --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/* \
 && pip install -q -r /tmp/requirements-dev.txt \
 && git config --system --add safe.directory /src
# Non-root by default; `make` additionally runs it as the invoking host uid:gid.
USER 10001:10001
WORKDIR /src

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
