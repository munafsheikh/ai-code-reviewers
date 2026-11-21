"""Repository tasks. Runs inside the toolbox container only; start it with ./run.sh or ./run.ps1.

Container and stack commands (build, up, down, e2e, security, deploy) run on the host with
`podman compose` and the scripts under infrastructure/ and tests/end-to-end/; see the README.
"""

from __future__ import annotations

import argparse
import glob
import shutil
import subprocess
import sys
from pathlib import Path

PY = sys.executable


def sh(*cmd: str) -> None:
    print("$ " + " ".join(cmd), file=sys.stderr, flush=True)
    rc = subprocess.run(list(cmd)).returncode
    if rc:
        sys.exit(rc)


def validate(a: argparse.Namespace) -> None:
    sh(PY, "-m", "orchestrator", "validate")
    sh(PY, "infrastructure/scripts/check_pins.py")
    sh(PY, "infrastructure/scripts/check_exceptions.py")


def lint(a: argparse.Namespace) -> None:
    sh("ruff", "check", ".")
    sh("ruff", "format", "--check", ".")


def fmt(a: argparse.Namespace) -> None:
    sh("ruff", "format", ".")
    sh("ruff", "check", "--fix", ".")


def test(a: argparse.Namespace) -> None:
    Path(a.out).mkdir(parents=True, exist_ok=True)
    sh("pytest", "--cov", "--cov-report=term", f"--cov-report=xml:{a.out}/coverage.xml", f"--junitxml={a.out}/junit.xml")


def test_fast(a: argparse.Namespace) -> None:
    sh("pytest", "tests/unit", "tests/contract", "tests/regression", "-q")


def test_security(a: argparse.Namespace) -> None:
    sh("pytest", "tests/security", "-q")


def test_resilience(a: argparse.Namespace) -> None:
    sh("pytest", "tests/unit/test_recovery.py", "tests/integration", "-q")


def schema_check(a: argparse.Namespace) -> None:
    files = sorted({f for p in a.files for f in (glob.glob(p) or [p])})
    sh(PY, "-m", "orchestrator.schema_check", *files)


def docs(a: argparse.Namespace) -> None:
    sh(PY, "-m", "orchestrator", "docs", "generate")


def docs_check(a: argparse.Namespace) -> None:
    sh(PY, "-m", "orchestrator", "docs", "check")
    sh(PY, "infrastructure/scripts/check_links.py")


def bench(a: argparse.Namespace) -> None:
    sh(PY, "-m", "orchestrator", "bench", "--profile", a.profile, *(["--gate"] if a.gate else []), "--out", f"{a.out}/bench.json", *a.extra)


def bench_gate(a: argparse.Namespace) -> None:
    a.gate = True
    bench(a)


def review_offline(a: argparse.Namespace) -> None:
    out = ["--format", "json,sarif,markdown,legacy", "--out-dir", a.out, "--stdout", "markdown"]
    sh(PY, "-m", "orchestrator", "review", "--profile", "offline", "--diff", a.diff, *out)


def evolve(a: argparse.Namespace) -> None:
    Path(a.out).mkdir(parents=True, exist_ok=True)
    sh(PY, "-m", "orchestrator", "evolve", "--out", f"{a.out}/proposal.md")


def ci(a: argparse.Namespace) -> None:
    for step in (validate, lint, test, docs_check, bench_gate):
        step(a)


def release(a: argparse.Namespace) -> None:
    # Pass-through: stdout is the release tool's own output (JSON, notes, KEY=VALUE lines).
    sys.exit(subprocess.run([PY, "infrastructure/scripts/release.py", *a.args]).returncode)


def clean(a: argparse.Namespace) -> None:
    for p in ("out", ".acr-cache", ".pytest_cache"):
        shutil.rmtree(p, ignore_errors=True)
    Path(".coverage").unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="run.sh", description="Repository tasks, run in the toolbox container.")
    sub = ap.add_subparsers(dest="task", required=True, metavar="TASK")

    def task(name: str, fn, help: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help)
        p.add_argument("--out", default="out", help="output directory (default: out)")
        p.set_defaults(fn=fn)
        return p

    task("validate", validate, "manifests, schemas, rule examples, wrapper permissions, fixtures, pins, exceptions")
    task("lint", lint, "ruff lint + format check")
    task("fmt", fmt, "apply formatting")
    task("test", test, "full test suite with coverage gate")
    task("test-fast", test_fast, "unit + contract + regression tests")
    task("test-security", test_security, "adversarial / untrusted-input suite")
    task("test-resilience", test_resilience, "fault injection: retry, circuit breaker, cache corruption, runtime loss, deadlines")
    task("schema-check", schema_check, "validate review result JSON files").add_argument("files", nargs="+")
    task("docs", docs, "regenerate docs/generated from source definitions")
    task("docs-check", docs_check, "fail if generated docs drifted or links are broken")
    for name, fn in (("bench", bench), ("bench-gate", bench_gate)):
        p = task(name, fn, "benchmarks" + (" + quality-gate thresholds" if fn is bench_gate else ""))
        p.add_argument("--profile", default="offline", help="profile (default: offline, deterministic)")
        p.set_defaults(gate=False)
    task("review-offline", review_offline, "review a diff, rules only, all formats into --out").add_argument(
        "--diff", default="examples/sample-repo/change.patch"
    )
    task("evolve", evolve, "evidence-based improvement proposal")
    p = task("ci", ci, "everything CI runs before the container jobs")
    p.add_argument("--profile", default="offline")
    p.set_defaults(gate=True)
    task("release", release, "release tool: plan | apply X.Y.Z | check X.Y.Z | notes X.Y.Z | image-tags ...").add_argument(
        "args", nargs=argparse.REMAINDER
    )
    task("clean", clean, "remove local build/test outputs")

    # Unknown options pass through to the bench tool (e.g. bench-gate --repeat 3); elsewhere they are errors.
    a, extra = ap.parse_known_args(argv)
    if extra and a.task not in ("bench", "bench-gate"):
        ap.error(f"unrecognized arguments: {' '.join(extra)}")
    a.extra = extra
    a.fn(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
