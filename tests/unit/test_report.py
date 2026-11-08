import json

from orchestrator.engine import report
from orchestrator.engine.review import run_review
from tests.conftest import fixture_diff


def result():
    return run_review(fixture_diff("java-leak-injection"), "offline")


def test_sarif_shape():
    s = json.loads(report.to_sarif(result()))
    assert s["version"] == "2.1.0"
    run = s["runs"][0]
    assert run["tool"]["driver"]["name"] == "ai-code-reviewers"
    ids = {r["id"] for r in run["tool"]["driver"]["rules"]}
    assert {r["ruleId"] for r in run["results"]} <= ids
    assert all(r["locations"][0]["physicalLocation"]["region"]["startLine"] >= 1 for r in run["results"])
    assert {r["level"] for r in run["results"]} <= {"error", "warning", "note"}


def test_markdown_and_legacy():
    r = result()
    md = report.to_markdown(r)
    assert "**BLOCK**" in md and "INJ-001" in md and "Sup3rS3cretDb" not in md
    legacy = report.to_legacy(r)
    assert legacy.startswith("SEVERITY: BLOCK\nSUMMARY: 4 finding(s)\nISSUES:\n")
