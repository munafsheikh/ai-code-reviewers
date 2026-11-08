# Security policy

## Reporting
Report vulnerabilities privately via GitHub Security Advisories
("Report a vulnerability" on the repository's Security tab). Do not open public issues.
Expect acknowledgement within 5 working days.

## Supported versions
The latest minor release receives fixes.

## Design commitments
- No telemetry, no external model calls, no source upload unless explicitly configured
  (`ACR_ALLOWED_HOSTS`, `ACR_ALLOW_PROXY`).
- Code under review is untrusted input: see the [threat model](docs/security/threat-model.md).
- Releases: SBOM attached, image signed with cosign keyless (GitHub OIDC). Verify with
  `cosign verify ghcr.io/munafsheikh/ai-code-reviewers@<digest> --certificate-identity-regexp '^https://github.com/munafsheikh/ai-code-reviewers/' --certificate-oidc-issuer https://token.actions.githubusercontent.com`.
- Scanning levels and the current baseline: [vulnerability baseline](docs/security/vulnerability-baseline.md).
