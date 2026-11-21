# A team's own reviewer: the published image plus baked-in review instructions and a custom
# deterministic rule. Nothing else changes; build once, run anywhere, offline.
#   docker build -t my-org/code-reviewer examples/custom-image
#   git diff main... | docker run --rm -i --read-only my-org/code-reviewer review --profile offline
ARG REVIEWER_IMAGE=munafsheikh/ai-code-reviewers:0.5.0
FROM ${REVIEWER_IMAGE}
COPY instructions.d/ /etc/acr/instructions.d/
COPY skills.d/ /etc/acr/skills.d/
# Fail the build if a rule's own examples do not behave as declared.
RUN acr validate --skip structure,fixtures
