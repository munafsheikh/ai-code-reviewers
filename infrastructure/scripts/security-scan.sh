#!/usr/bin/env bash
# Layered security scan with pinned scanner images (same commands locally and in any CI).
#   security-scan.sh [IMAGE] [all|secrets|sast|deps|dockerfile|image|sbom]
# Reports go to out/security/. Exit non-zero when a scanner reports findings at or
# above the configured threshold (policies/security/scanners.env). Known findings are
# tracked in policies/security/ (never silently suppressed).
set -euo pipefail
cd "$(dirname "$0")/../.."
IMAGE="${1:-acr-reviewer:local}"
WHAT="${2:-all}"
OUT="out/security"
mkdir -p "$OUT"
# shellcheck source=/dev/null
source policies/security/scanners.env

GITLEAKS=zricethezav/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f
TRIVY=aquasec/trivy:0.76.2@sha256:8f6bb947dbc528902e11f2f5be52f7b519f6a39d5d148f41166f2040499768fb
HADOLINT=hadolint/hadolint:v2.15.1@sha256:32dac94127fd60b7b7e3fbfc65e1383b9b5e25c9bfd7b8536de7a539fe68a12d
SEMGREP=semgrep/semgrep:1.184.0@sha256:cc1b68266f267878b39739373ea9985b9a78e5d64497dd875c8de100b22695ed

status=0
run() { local name=$1; shift; echo "::group::$name"; if "$@"; then echo "[security] $name: pass"; else echo "[security] $name: FINDINGS (see $OUT)"; status=1; fi; echo "::endgroup::"; }
# SCAN_DOCKER_ARGS: extra `docker run` flags, e.g. for corporate proxies / custom CA bundles.
read -r -a EXTRA <<< "${SCAN_DOCKER_ARGS:-}"
D=(docker run --rm "${EXTRA[@]}" -v "$PWD:/src:ro" -w /src)
TRIVY_CACHE=(-v acr-trivy-cache:/root/.cache/trivy)

secrets()    { "${D[@]}" -v "$PWD/$OUT:/out" "$GITLEAKS" dir /src --config /src/.gitleaks.toml --redact --no-banner \
                 --report-format sarif --report-path /out/gitleaks.sarif; }
sast()       { "${D[@]}" -v "$PWD/$OUT:/out" "$SEMGREP" semgrep scan --metrics=off --disable-version-check \
                 --config /src/policies/security/semgrep.yml --severity "$SEMGREP_FAIL_SEVERITY" --error \
                 --sarif --output /out/semgrep.sarif --exclude benchmarks/fixtures --exclude tests /src; }
dockerfile() { docker run --rm "${EXTRA[@]}" -i -v "$PWD/.hadolint.yaml:/.config/hadolint.yaml:ro" "$HADOLINT" \
                 hadolint --failure-threshold "$HADOLINT_FAIL_THRESHOLD" - < infrastructure/docker/Dockerfile \
              && docker run --rm "${EXTRA[@]}" -i -v "$PWD/.hadolint.yaml:/.config/hadolint.yaml:ro" "$HADOLINT" \
                 hadolint --failure-threshold "$HADOLINT_FAIL_THRESHOLD" - < infrastructure/docker/Dockerfile.toolbox; }
deps()       { "${D[@]}" "${TRIVY_CACHE[@]}" -v "$PWD/$OUT:/out" "$TRIVY" fs --scanners vuln,misconfig --exit-code 1 \
                 --severity "$TRIVY_FAIL_SEVERITY" --ignorefile /src/policies/security/trivyignore --secret-config /src/policies/security/trivy-secret.yaml --skip-dirs benchmarks/fixtures \
                 --format sarif --output /out/trivy-fs.sarif /src; }
image()      { docker run --rm "${EXTRA[@]}" "${TRIVY_CACHE[@]}" -v /var/run/docker.sock:/var/run/docker.sock:ro -v "$PWD/$OUT:/out" \
                 -v "$PWD/policies/security:/policy:ro" "$TRIVY" image --exit-code 1 --severity "$TRIVY_FAIL_SEVERITY" \
                 --ignore-unfixed --ignorefile /policy/trivyignore --secret-config /policy/trivy-secret.yaml --format sarif --output /out/trivy-image.sarif "$IMAGE"; }
sbom()       { docker run --rm "${EXTRA[@]}" "${TRIVY_CACHE[@]}" -v /var/run/docker.sock:/var/run/docker.sock:ro -v "$PWD/$OUT:/out" \
                 "$TRIVY" image --format cyclonedx --output /out/sbom.cdx.json "$IMAGE"; }

case "$WHAT" in
  all) run secrets secrets; run sast sast; run dockerfile dockerfile; run deps deps; run image image; run sbom sbom ;;
  *) run "$WHAT" "$WHAT" ;;
esac
exit $status
