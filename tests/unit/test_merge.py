"""Parallel review lanes merge into one result that matches a single full review."""

import json

from orchestrator import config as cfg
from orchestrator import schema
from orchestrator.cli import main as cli
from orchestrator.engine.merge import merge_results
from orchestrator.engine.review import run_review

LANES = {
    "code": "code-quality.*,maintainability.*,testing.*,architecture.*,performance.*,lang.*",
    "security": "security.*",
    "docs": "documentation.*,refinement.*",
}
DIFF = (
    "--- a/app/db.py\n+++ b/app/db.py\n@@ -0,0 +1,3 @@\n"
    "+def find(cur, name):\n+    cur.execute(\"SELECT * FROM t WHERE n = '%s'\" % name)\n+    breakpoint()\n"
    "--- a/README.md\n+++ b/README.md\n@@ -0,0 +1 @@\n+Usage: TBD\n"
)


def _lanes(monkeypatch):
    out = []
    for skills in LANES.values():
        monkeypatch.setenv("ACR_SKILLS", skills)
        out.append(run_review(DIFF, profile_name="offline"))
    monkeypatch.delenv("ACR_SKILLS")
    return out


def test_lanes_merge_to_the_same_findings_as_one_review(monkeypatch):
    lanes = _lanes(monkeypatch)
    whole = run_review(DIFF, profile_name="offline")
    merged = merge_results(lanes, cfg.load_policy("default"), list(LANES))
    assert schema.validate(merged, schema.load("review-result")) == []
    assert sorted(f["fingerprint"] for f in merged["findings"]) == sorted(f["fingerprint"] for f in whole["findings"])
    assert merged["gate"]["status"] == whole["gate"]["status"] == "block"
    assert [ln["name"] for ln in merged["run"]["lanes"]] == ["code", "security", "docs"]


def test_coverage_is_judged_across_lanes(monkeypatch):
    lanes = _lanes(monkeypatch)
    # Alone, the docs lane leaves the code file uncovered and the security lane leaves the doc file.
    assert "app/db.py" in lanes[2]["run"]["coverage"]["uncovered"]
    assert "README.md" in lanes[1]["run"]["coverage"]["uncovered"]
    merged = merge_results(lanes, cfg.load_policy("default"))
    assert merged["run"]["coverage"]["uncovered"] == []
    assert not any("coverage" in r for r in merged["gate"]["reasons"])


def test_missing_lane_leaves_a_coverage_gap_that_blocks(monkeypatch):
    lanes = _lanes(monkeypatch)
    clean = "--- a/README.md\n+++ b/README.md\n@@ -0,0 +1 @@\n+All good.\n"
    monkeypatch.setenv("ACR_SKILLS", LANES["code"])
    only_code = run_review(clean, profile_name="offline")
    merged = merge_results([only_code], cfg.load_policy("default"), ["code"])
    assert merged["gate"]["status"] == "block"
    assert merged["gate"]["reasons"] == ["no documentation review coverage for README.md"]
    assert lanes  # fixture used


def test_duplicate_findings_keep_the_highest_severity(monkeypatch):
    a = run_review(DIFF, profile_name="offline")
    b = json.loads(json.dumps(a))
    for f in b["findings"]:
        f["severity"] = "info"
    merged = merge_results([b, a], cfg.load_policy("default"))
    assert len(merged["findings"]) == len(a["findings"])
    assert {f["severity"] for f in merged["findings"]} == {f["severity"] for f in a["findings"]}


def test_cli_merge(tmp_path, monkeypatch, capsys):
    paths = []
    for name, r in zip(LANES, _lanes(monkeypatch), strict=True):
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(r))
        paths.append(str(p))
    out = tmp_path / "merged"
    code = cli.main(["merge", *paths, "--names", "code,security,docs", "--format", "json,markdown", "--out-dir", str(out)])
    assert code == 1  # blocked: injection + debugger + placeholder
    md = (out / "review.md").read_text()
    assert "Parallel reviews: code" in md and "security" in md and "docs" in md
    assert cli.main(["merge", str(tmp_path / "missing.json")]) == 2
    assert cli.main(["merge", *paths, "--names", "only-one"]) == 2
