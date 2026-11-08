# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
# Reviewer image: stdlib-only Python, non-root, read-only friendly, no build tools at runtime.
ARG PYTHON_IMAGE=python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
FROM ${PYTHON_IMAGE}

ARG VERSION=0.0.0-dev
ARG REVISION=unknown
LABEL org.opencontainers.image.title="ai-code-reviewers" \
      org.opencontainers.image.description="Offline, model-agnostic AI code review" \
      org.opencontainers.image.source="https://github.com/munafsheikh/ai-code-reviewers" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ACR_HOME=/opt/acr \
    PYTHONPATH=/opt/acr \
    ACR_CACHE_DIR=/var/cache/acr \
    ACR_BIND=0.0.0.0

# No git, compilers or package manager use at runtime: diffs arrive on stdin or over HTTP.
# pip/setuptools are not needed at runtime and carry their own CVEs (vendored urllib3, msgpack).
RUN python -m pip uninstall -y -q pip setuptools wheel 2>/dev/null; \
    rm -rf /usr/local/lib/python3.13/ensurepip \
 && groupadd --system --gid 10001 acr \
 && useradd --system --uid 10001 --gid acr --home-dir /nonexistent --shell /usr/sbin/nologin acr \
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
