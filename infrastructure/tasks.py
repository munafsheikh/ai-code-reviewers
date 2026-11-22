"""Development and CI tasks. Docker is the only host requirement:

    docker compose run --rm dev <task> [options]      (from the repository root)
    docker compose run --rm dev help                  lists the tasks
    COMPOSE_PROGRESS=quiet ...                        when capturing stdout (keeps build progress out of it)

The `dev` Compose service is the toolbox image (pinned Python tooling, git, Docker CLI) with the
repository mounted at the host's own path and the host's Docker socket, so tasks that build,
scan or run containers pass paths the host daemon understands. CI runs exactly these commands.
Stdlib only; each task is a native command (pytest, ruff, mkdocs, python -m orchestrator, the
repository's scripts) run inside the container.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = "infrastructure/docker/Dockerfile"
TASKS: dict[str, tuple[str, callable]] = {}
PASSTHROUGH = {"release", "py", "schema-check"}  # every argument after the task goes to the command


def task(name: str, help_: str):
    def deco(fn):
        TASKS[name] = (help_, fn)
        return fn

    return deco


def sh(*cmd: str, check: bool = True, **kw) -> int:
    print("+ " + " ".join(cmd), file=sys.stderr, flush=True)
    rc = subprocess.run(list(cmd), cwd=ROOT, **kw).returncode
    if check and rc:
        raise SystemExit(rc)
    return rc


def acr(*args: str, **kw) -> int:
    return sh(sys.executable, "-m", "orchestrator", *args, **kw)


def script(path: str, *args: str) -> int:
    return sh(str(ROOT / path), *args)


def revision() -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    return r.stdout.strip() or "unknown"


# --- checks ------------------------------------------------------------------------------


@task("lint", "ruff lint + format check")
def lint(a):
    sh("ruff", "check", ".")
    sh("ruff", "format", "--check", ".")


@task("fmt", "apply formatting and safe lint fixes")
def fmt(a):
    sh("ruff", "format", ".")
    sh("ruff", "check", "--fix", ".")


@task("validate", "manifests, schemas, rule examples, wrapper permissions, fixtures, pins, exceptions")
def validate(a):
    acr("validate")
    sh(sys.executable, "infrastructure/scripts/check_pins.py")
    sh(sys.executable, "infrastructure/scripts/check_exceptions.py")


@task("test", "full test suite with coverage gate (reports in OUT)")
def test(a):
    Path(ROOT / a.out).mkdir(parents=True, exist_ok=True)
    sh("pytest", "--cov", "--cov-report=term", f"--cov-report=xml:{a.out}/coverage.xml", f"--junitxml={a.out}/junit.xml", *a.rest)


@task("test-fast", "unit + contract + regression tests")
def test_fast(a):
    sh("pytest", "tests/unit", "tests/contract", "tests/regression", "-q", *a.rest)


@task("test-security", "adversarial / untrusted-input suite")
def test_security(a):
    sh("pytest", "tests/security", "-q", *a.rest)


@task("test-resilience", "fault injection: retry, circuit breaker, cache corruption, runtime loss, deadlines")
def test_resilience(a):
    sh("pytest", "tests/unit/test_recovery.py", "tests/integration", "-q", *a.rest)


@task("schema-check", "validate review result JSON files: schema-check out/reviews/*/review.json")
def schema_check(a):
    sh(sys.executable, "-m", "orchestrator.schema_check", *a.rest)


@task("docs", "regenerate docs/generated from source definitions")
def docs(a):
    acr("docs", "generate")


@task("docs-check", "fail if generated docs drifted or links are broken")
def docs_check(a):
    acr("docs", "check")
    sh(sys.executable, "infrastructure/scripts/check_links.py")


@task("docs-site", "build the documentation site (MkDocs, strict) into OUT/site")
def docs_site(a):
    sh("mkdocs", "build", "--strict", "--config-file", "infrastructure/docs/mkdocs.yml", "--site-dir", str(ROOT / a.out / "site"))


@task("bench", "run the benchmarks (--profile, default offline: deterministic)")
def bench(a):
    acr("bench", "--profile", a.profile or "offline", "--out", f"{a.out}/bench.json", *a.rest)


@task("bench-gate", "benchmarks + quality-gate thresholds")
def bench_gate(a):
    acr("bench", "--profile", a.profile or "offline", "--gate", "--out", f"{a.out}/bench.json", *a.rest)


@task("ci", "everything the test job runs: validate, lint, test, docs-check, bench-gate")
def ci(a):
    for t in (validate, lint, test, docs_check, bench_gate):
        t(argparse.Namespace(**{**vars(a), "rest": []}))


@task("review-offline", "review --diff (rules only) into OUT in every format")
def review_offline(a):
    acr(
        "review",
        "--profile",
        "offline",
        "--diff",
        a.diff,
        "--format",
        "json,sarif,markdown,legacy",
        "--out-dir",
        a.out,
        "--stdout",
        "markdown",
    )


@task("evolve", "evidence-based improvement proposal (OUT/proposal.md)")
def evolve(a):
    Path(ROOT / a.out).mkdir(parents=True, exist_ok=True)
    acr("evolve", "--out", f"{a.out}/proposal.md")


@task("release", "release tooling: release plan|apply|check|notes|image-tags ... (infrastructure/scripts/release.py)")
def release(a):
    sh(sys.executable, "infrastructure/scripts/release.py", *a.rest)


@task("py", "run Python in the toolbox: py script.py ARGS | py -c CODE | py - < script")
def py(a):
    sh(sys.executable, *a.rest)


# --- images and containers (host Docker through the socket) -------------------------------


@task("build", "build the reviewer image (--image)")
def build(a):
    sh("docker", "build", "-f", DOCKERFILE, "--target", "reviewer", "-t", a.image, "--build-arg", f"REVISION={revision()}", ".")


@task("runtime", "build the model runtime with --models baked in (downloads once, at build time)")
def runtime(a):
    extra = ["--build-arg", f"MODELS={a.models}"] if a.models else []
    sh("docker", "build", "-f", DOCKERFILE, "--target", "runtime", *extra, "-t", a.runtime_image, ".")


@task("images", "build every Python image locally as acr-<target>:local")
def images(a):
    for t in ("base", "reviewer", "toolbox", "fake-runtime"):
        sh("docker", "build", "-q", "-f", DOCKERFILE, "--target", t, "-t", f"acr-{t}:local", ".")


@task("smoke", "smoke-test a running stack ($BASE_URL, default http://127.0.0.1:8088)")
def smoke(a):
    script("infrastructure/scripts/smoke.sh")


@task("e2e", "build, start with the fake runtime, smoke, review fixtures in the container, tear down")
def e2e(a):
    script("tests/end-to-end/compose_e2e.sh")


@task("resilience", "watchdog bounded restart + circuit breaker, deploy auto-rollback")
def resilience(a):
    script("tests/end-to-end/resilience.sh")


@task("prove-offline", "prove reviews cannot leave the machine (--image, --runtime-image, --diff)")
def prove_offline(a):
    script("infrastructure/scripts/prove-offline.sh", a.image, a.runtime_image, a.diff)


@task("security", "secrets, SAST, dependency, Dockerfile and image scans (--image; --what one of them)")
def security(a):
    script("infrastructure/scripts/security-scan.sh", a.image, a.what or "all")


@task("deploy-test", "deploy --image to a disposable test environment; smoke; auto-rollback on failure")
def deploy_test(a):
    script("infrastructure/deployment/deploy.sh", a.image)


@task("teardown", "remove the disposable test environment")
def teardown(a):
    script("infrastructure/deployment/teardown.sh")


@task("rollback", "roll the test environment back to the last verified release")
def rollback(a):
    script("infrastructure/deployment/rollback.sh")


@task("watchdog", "one bounded health/recovery pass over the running stack")
def watchdog(a):
    script("infrastructure/monitoring/watchdog.sh")


# --- misc --------------------------------------------------------------------------------


@task("shell", "interactive shell in the toolbox")
def shell(a):
    sh("bash", check=False)


@task("clean", "remove local build and test outputs")
def clean(a):
    for p in ("out", ".acr-cache", ".pytest_cache", ".coverage", ".ruff_cache"):
        t = ROOT / p
        shutil.rmtree(t, ignore_errors=True) if t.is_dir() else t.unlink(missing_ok=True)


@task("help", "list the tasks")
def help_(a):
    print(__doc__.strip() + "\n\nTasks:")
    for name, (h, _) in TASKS.items():
        print(f"  {name:<16} {h}")
    print("\nOptions: --out DIR (out)  --diff FILE  --image REF (acr-reviewer:local)  --runtime-image REF (acr-runtime:local)")
    print("         --models 'ref ...'  --profile ID  --what CHECK")
    print("Other arguments go to pytest (test*), bench (bench*), or, for release/py/schema-check, the command.")


def _hand_back(root: Path) -> None:
    """Running as root (for the Docker socket): return created files to the repository's owner."""
    if os.name != "posix" or os.geteuid() != 0:
        return
    st = root.stat()
    if st.st_uid == 0:
        return
    for d, dirs, files in os.walk(root):
        for n in [*dirs, *files]:
            p = os.path.join(d, n)
            try:
                s = os.lstat(p)
                if s.st_uid != st.st_uid:
                    os.lchown(p, st.st_uid, st.st_gid)
            except OSError:
                pass
    try:
        os.lchown(root, st.st_uid, st.st_gid)
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="docker compose run --rm dev", add_help=False)
    ap.add_argument("task", nargs="?", default="help", choices=list(TASKS))
    ap.add_argument("--out", default="out")
    ap.add_argument("--diff", default="examples/sample-repo/change.patch")
    ap.add_argument("--image", default="acr-reviewer:local")
    ap.add_argument("--runtime-image", default="acr-runtime:local")
    ap.add_argument("--models", default="")
    ap.add_argument("--profile", default="")
    ap.add_argument("--what", default="")
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in PASSTHROUGH:
        a = ap.parse_args(argv[:1])
        a.rest = argv[1:]
    else:
        a, a.rest = ap.parse_known_args(argv)
    if not (ROOT / "compose.yaml").is_file():
        print("run from the repository root", file=sys.stderr)
        return 2
    try:
        TASKS[a.task][1](a)
        return 0
    except SystemExit as e:
        return int(e.code or 0)
    finally:
        _hand_back(ROOT)


if __name__ == "__main__":
    sys.exit(main())
