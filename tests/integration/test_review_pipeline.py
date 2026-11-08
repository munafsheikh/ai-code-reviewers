"""Engine + wrapper + fake runtime over real HTTP."""

import json
import os
import subprocess
import sys
import threading
import urllib.request

import pytest

from orchestrator import config as cfg
from orchestrator.engine.review import run_review
from tests.conftest import fixture_diff


def test_balanced_review_merges_rule_and_model_findings(runtime):
    r = run_review(fixture_diff("java-leak-injection"), "balanced")
    assert r["gate"]["status"] == "block" and not r["run"]["degraded"]
    assert r["run"]["calls"]["total"] == 1
    inj = next(f for f in r["findings"] if f["rule_id"] == "INJ-001")
    assert inj["corroborated_by"], "model finding on the same line should corroborate the rule"
    assert r["run"]["models"][0]["ref"] == "qwen2.5-coder:1.5b"


def test_second_run_is_served_from_cache(runtime):
    run_review(fixture_diff("java-leak-injection"), "balanced")
    r = run_review(fixture_diff("java-leak-injection"), "balanced")
    assert r["run"]["calls"]["cached"] == 1


def test_transient_failure_is_retried_and_audited(runtime, monkeypatch, fast_retry):
    monkeypatch.setenv("FAKE_FAIL_FIRST_N", "2")
    r = run_review(fixture_diff("python-unsafe"), fast_retry)
    actions = [e["action"] for e in r["run"]["recovery_events"]]
    assert actions.count("retry") == 2 and not r["run"]["degraded"]


def test_runtime_down_degrades_to_rules_only(monkeypatch, fast_retry):
    monkeypatch.setenv("ACR_MODEL_HOST", "http://127.0.0.1:9")
    r = run_review(fixture_diff("python-unsafe"), fast_retry)
    assert r["run"]["degraded"] and r["gate"]["status"] == "block"
    assert "fallback_rules_only" in [e["action"] for e in r["run"]["recovery_events"]]
    assert all(f["source"] == "rule" for f in r["findings"])


def test_strict_policy_fails_when_runtime_down(monkeypatch, fast_retry):
    monkeypatch.setenv("ACR_MODEL_HOST", "http://127.0.0.1:9")
    r = run_review(fixture_diff("python-clean"), fast_retry, policy_name="strict")
    assert r["gate"]["exit_code"] == 2


def test_model_call_budget_is_enforced(runtime, tmp_path):
    p = tmp_path / "p.toml"
    p.write_text('extends = "balanced"\nid = "tiny"\n[budget]\nmax_model_calls = 1\nmax_diff_chars = 1000\n')
    big = "".join(fixture_diff(c) for c in ("java-leak-injection", "python-unsafe", "js-xss-focused-test"))
    r = run_review(big, str(p))
    assert r["run"]["calls"]["total"] == 1
    assert "budget_limited" in [e["action"] for e in r["run"]["recovery_events"]]
    assert r["run"]["source"]["files_skipped"]  # never silent


def test_model_digest_mismatch_disables_model(runtime, tmp_path, monkeypatch):
    root = tmp_path / "home"
    import shutil

    shutil.copytree(cfg.home(), root, ignore=shutil.ignore_patterns(".git", ".acr-cache", "__pycache__", ".venv"))
    mf = root / "models/registry/qwen2.5-coder-1.5b.toml"
    mf.write_text(mf.read_text().replace('digest = ""', 'digest = "sha256:' + "f" * 64 + '"'))
    r = run_review(fixture_diff("python-unsafe"), "balanced", root=root)
    assert "model_integrity_mismatch" in [e["action"] for e in r["run"]["recovery_events"]]
    assert r["run"]["degraded"] and all(f["source"] == "rule" for f in r["findings"])


def test_cli_writes_all_formats(runtime, tmp_path):
    out = tmp_path / "out"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "orchestrator",
            "review",
            "--profile",
            "offline",
            "--diff",
            str(cfg.home() / "benchmarks/fixtures/secrets-config/diff.patch"),
            "--format",
            "json,sarif,markdown,legacy",
            "--out-dir",
            str(out),
        ],
        capture_output=True,
        text=True,
        cwd=cfg.home(),
        env=os.environ,
    )
    assert proc.returncode == 1
    assert {p.name for p in out.iterdir()} == {"review.json", "review.sarif", "review.md", "review.txt"}
    assert json.loads((out / "review.sarif").read_text())["version"] == "2.1.0"


def test_cli_git_range(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    git = ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run([*git, "init", "-q"], check=True)
    (repo / "a.py").write_text("x = 1\n")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "1"], check=True)
    (repo / "a.py").write_text("x = 1\nresult = eval(data)\n")
    subprocess.run([*git, "commit", "-qam", "2"], check=True)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "orchestrator",
            "review",
            "--profile",
            "offline",
            "--repo",
            str(repo),
            "--git-range",
            "HEAD~1...HEAD",
            "--format",
            "legacy",
        ],
        capture_output=True,
        text=True,
        cwd=cfg.home(),
    )
    assert proc.returncode == 1 and "INJ-002" not in proc.stdout and "a.py:2" in proc.stdout


@pytest.fixture
def service(runtime):
    from http.server import ThreadingHTTPServer

    from orchestrator.cli import serve

    serve.Handler.default_profile = "balanced"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _req(url, data=None, ctype="text/plain"):
    req = urllib.request.Request(url, data=data, headers={"Content-Type": ctype})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=30) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_service_endpoints(service):
    assert _req(service + "/healthz")[0] == 200
    code, body = _req(service + "/readyz")
    assert code == 200 and json.loads(body)["status"] == "ready"
    code, body = _req(service + "/v1/review", fixture_diff("python-unsafe").encode())
    assert code == 200 and json.loads(body)["gate"]["status"] == "block"
    code, body = _req(
        service + "/v1/review",
        json.dumps({"diff": fixture_diff("python-clean"), "format": "sarif", "profile": "offline"}).encode(),
        "application/json",
    )
    assert code == 200 and json.loads(body)["version"] == "2.1.0"
    metrics = _req(service + "/metrics")[1]
    assert "acr_reviews_total 2" in metrics
