"""Minimum confidence: defaults, precedence, filtering, effect on the gate, traceability."""

import json

import pytest

from orchestrator import config as cfg
from orchestrator.cli import main as cli
from orchestrator.cli import validate
from orchestrator.engine import confidence
from orchestrator.engine.merge import merge_results
from orchestrator.engine.review import run_review

# INJ-003 (critical, medium confidence: hypothesis), ERR-001 (major, high: verified), PY-001 (minor, high)
DIFF = (
    "--- a/svc/jobs.py\n+++ b/svc/jobs.py\n@@ -0,0 +1,7 @@\n"
    "+def run(cmd, env={}):\n+    return subprocess.run(cmd, shell=True, env=env)\n+\n+\n"
    "+def go():\n+    try:\n+        x()\n"
    "--- a/svc/more.py\n+++ b/svc/more.py\n@@ -0,0 +1,4 @@\n+try:\n+    go()\n+except Exception:\n+    pass\n"
)


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    monkeypatch.delenv("ACR_MIN_CONFIDENCE", raising=False)


def test_defaults_and_precedence():
    pol = {"id": "p", "gate": {"min_confidence": "medium"}}
    assert confidence.resolve({"id": "x", "gate": {}}, None, {}) == ("low", "default")
    assert confidence.resolve(pol, None, {}) == ("medium", "policy p")
    assert confidence.resolve(pol, None, {"ACR_MIN_CONFIDENCE": "high"}) == ("high", "ACR_MIN_CONFIDENCE")
    assert confidence.resolve(pol, "low", {"ACR_MIN_CONFIDENCE": "high"}) == ("low", "--min-confidence")
    with pytest.raises(confidence.ConfidenceError):
        confidence.resolve(pol, None, {"ACR_MIN_CONFIDENCE": "sure"})


def test_shipped_policies_default_to_reporting_everything():
    for name in ("default", "strict", "evaluation"):
        assert cfg.load_policy(name)["gate"]["min_confidence"] == "low"


def test_default_reports_everything_and_records_it():
    r = run_review(DIFF, profile_name="offline")
    assert {"INJ-003", "ERR-001", "PY-001"} <= {f["rule_id"] for f in r["findings"]}
    assert r["run"]["confidence"] == {
        "min": "low",
        "source": "policy default",
        "hidden": 0,
        "hidden_by_severity": {"critical": 0, "major": 0, "minor": 0, "info": 0},
    }


def test_high_minimum_hides_hypotheses_and_they_no_longer_block():
    r = run_review(DIFF, profile_name="offline", min_confidence="high")
    assert {f["confidence"] for f in r["findings"]} == {"high"}
    assert "INJ-003" not in {f["rule_id"] for f in r["findings"]}
    conf = r["run"]["confidence"]
    assert conf["min"] == "high" and conf["source"] == "--min-confidence"
    assert conf["hidden_by_severity"]["critical"] >= 1  # never silent: the hidden critical is counted
    assert not any("INJ-003" in reason for reason in r["gate"]["reasons"])
    assert r["gate"]["status"] == "block"  # ERR-001 (verified, major) still blocks


def test_env_overrides_policy(monkeypatch):
    monkeypatch.setenv("ACR_MIN_CONFIDENCE", "high")
    r = run_review(DIFF, profile_name="offline")
    assert r["run"]["confidence"]["source"] == "ACR_MIN_CONFIDENCE"
    assert all(f["confidence"] == "high" for f in r["findings"])


def test_merge_applies_the_higher_minimum_and_adds_up_hidden(monkeypatch):
    lanes = []
    for skills in ("code-quality.*,lang.*", "security.*"):
        monkeypatch.setenv("ACR_SKILLS", skills)
        lanes.append(run_review(DIFF, profile_name="offline", min_confidence="high"))
    monkeypatch.delenv("ACR_SKILLS")
    hidden_in_lanes = sum(ln["run"]["confidence"]["hidden"] for ln in lanes)
    merged = merge_results(lanes, cfg.load_policy("default"))
    assert merged["run"]["confidence"]["min"] == "high"
    assert merged["run"]["confidence"]["hidden"] == hidden_in_lanes
    assert all(f["confidence"] == "high" for f in merged["findings"])


def test_merge_can_raise_the_minimum():
    r = run_review(DIFF, profile_name="offline")
    merged = merge_results([r], cfg.load_policy("default"), min_confidence="high")
    assert all(f["confidence"] == "high" for f in merged["findings"])
    assert merged["run"]["confidence"]["source"] == "--min-confidence" and merged["run"]["confidence"]["hidden"] > 0


def test_cli_flag_report_and_bad_env(tmp_path, monkeypatch, capsys):
    d = tmp_path / "d.patch"
    d.write_text(DIFF)
    out = tmp_path / "out"
    assert (
        cli.main(
            [
                "review",
                "--profile",
                "offline",
                "--diff",
                str(d),
                "--min-confidence",
                "high",
                "--format",
                "json,markdown",
                "--out-dir",
                str(out),
            ]
        )
        == 1
    )
    assert json.loads((out / "review.json").read_text())["run"]["confidence"]["min"] == "high"
    assert "Minimum confidence: high (from --min-confidence); hidden below it: 1 critical" in (out / "review.md").read_text()
    monkeypatch.setenv("ACR_MIN_CONFIDENCE", "certain")
    assert cli.main(["review", "--profile", "offline", "--diff", str(d)]) == 2
    assert "confidence must be one of low, medium, high" in capsys.readouterr().err


def test_validate_rejects_a_bad_policy_value(tmp_path):
    pol = tmp_path / "policies" / "review"
    pol.mkdir(parents=True)
    (pol / "x.toml").write_text('id = "x"\nversion = "1.0.0"\n[gate]\nmin_confidence = "certain"\n')
    r = validate.Report()
    validate.check_policies(tmp_path, r)
    assert r.errors == ["policies/review/x.toml: gate.min_confidence must be low, medium or high, not 'certain'"]
