"""Lifecycle artifacts: GitHub issues reviewed at the refinement stage."""

import json

import pytest

from orchestrator import config as cfg
from orchestrator.cli import validate
from orchestrator.cli.main import main
from orchestrator.engine import artifact, coverage, diff, gate
from orchestrator.engine.review import run_review
from orchestrator.engine.rules import expectation_fires, run_expectations

READY = {
    "number": 12,
    "title": "Add CSV export",
    "labels": [{"name": "enhancement"}],
    "url": "https://github.com/o/r/issues/12",
    "body": "Finance needs report data in spreadsheets.\n\n## Acceptance criteria\n- [ ] Export downloads a .csv with one row per invoice",
}
BUG_SCREENSHOT = {
    "number": 7,
    "title": "Fix this",
    "labels": ["bug"],
    "body": "![image](https://github.com/user-attachments/assets/abc)",
}


def _review(issue, profile="offline", **kw):
    return run_review(artifact.issue_diff(issue), profile_name=profile, **kw)


def _ids(result):
    return {f["rule_id"] for f in result["findings"]}


def test_renders_gh_rest_and_webhook_shapes_identically():
    rest = dict(READY, url="https://api.github.com/repos/o/r/issues/12", html_url="https://github.com/o/r/issues/12")
    shapes = [READY, rest, {"action": "opened", "issue": rest}]
    rendered = {artifact.render_github_issue(s) for s in shapes}
    assert len(rendered) == 1
    path, text = rendered.pop()
    assert path == "@issue/12"
    assert text.splitlines()[:3] == ["# Add CSV export", "Labels: enhancement", "Issue: https://github.com/o/r/issues/12"]


def test_rejects_objects_that_are_not_issues():
    with pytest.raises(ValueError, match="not a GitHub issue"):
        artifact.render_github_issue({"title": "no number"})


def test_issue_becomes_one_added_file_with_every_line_numbered():
    files = diff.parse(artifact.issue_diff(READY))
    assert [f.path for f in files] == ["@issue/12"]
    assert files[0].added[0] == (1, "# Add CSV export")
    assert artifact.anchor(files[0].added, len(files[0].added)) == "Acceptance criteria"


def test_ready_issue_passes():
    result = _review(READY, repository="https://github.com/o/r")
    assert result["gate"]["status"] == "pass" and result["findings"] == []
    assert result["run"]["coverage"]["files"] == [{"path": "@issue/12", "kind": "artifact", "categories": ["refinement"], "covered": True}]


def test_screenshot_only_bug_is_blocked_with_links_to_the_issue():
    result = _review(BUG_SCREENSHOT, repository="https://github.com/o/r", revision="abc")
    assert _ids(result) == {"REF-102", "REF-103", "REF-104"}
    assert result["gate"]["status"] == "block"
    assert {f["links"]["location"] for f in result["findings"]} == {"https://github.com/o/r/issues/7"}
    assert {f["location"]["anchor"] for f in result["findings"]} == {"Fix this"}


def test_feature_without_acceptance_criteria_or_with_placeholders():
    vague = dict(READY, body="Make export fast and user-friendly.\n\nFormat: TBD")
    result = _review(vague)
    assert _ids(result) == {"REF-001", "REF-002", "REF-101"}
    assert {"REF-101", "REF-105"} <= _ids(_review(dict(READY, body="")))


def test_code_skills_never_review_artifacts_and_refinement_never_reviews_code():
    skills = cfg.load_skills()
    issue = diff.parse(artifact.issue_diff(dict(READY, body='password = "hunter2hunter2"\n\n## Acceptance criteria\n- [ ] x')))
    code = diff.parse("--- a/a.py\n+++ b/a.py\n@@ -0,0 +1 @@\n+# Add export TBD\n")
    reaching_issue = {s.id for s in skills.values() if issue[0].matches(s.file_globs, s.languages, s.exclude_globs)}
    assert reaching_issue == {"refinement.issue"}
    assert run_expectations(skills["refinement.issue"], code) == []


def test_artifact_needs_its_stage_check_for_coverage():
    files = diff.parse(artifact.issue_diff(READY))
    cov = coverage.compute(cfg.select_skills(["security.*"], cfg.load_skills()), files, set())
    assert cov["uncovered"] == ["@issue/12"] and cov["by_kind"]["artifact"] == 1
    g = gate.evaluate([], {"gate": {"require_coverage": True}}, [], cov["uncovered"])
    assert g["reasons"] == ["no refinement review coverage for @issue/12"]


def test_expectation_scoping():
    e = {"pattern": "steps", "when": "bug", "unless": "wontfix"}
    assert expectation_fires(e, "a bug")
    assert not expectation_fires(e, "a bug with steps")
    assert not expectation_fires(e, "a feature")
    assert not expectation_fires(e, "a bug, wontfix")


def test_validate_rejects_expectation_examples_that_misbehave():
    r = validate.Report()
    validate.check_expectation("x/skill.toml", {"id": "X-001", "pattern": "ok", "examples": {"flag": ["ok"], "pass": ["no"]}}, r)
    assert len(r.errors) == 2
    r = validate.Report()
    validate.check_expectation("x/skill.toml", {"id": "X-002", "pattern": "("}, r)
    validate.check_expectation("x/skill.toml", {"id": "X-003"}, r)
    assert len(r.errors) == 2


def test_web_url_only_for_issue_paths_on_web_repositories():
    assert artifact.web_url("https://github.com/o/r.git", "@issue/3") == "https://github.com/o/r/issues/3"
    assert artifact.web_url("git@github.com:o/r.git", "@issue/3") is None
    assert artifact.web_url("https://github.com/o/r", "src/a.py") is None


def test_cli_reviews_issue_from_file_and_stdin(tmp_path, capsys, monkeypatch):
    p = tmp_path / "issue.json"
    p.write_text(json.dumps(BUG_SCREENSHOT))
    assert main(["review", "--issue", str(p), "--profile", "offline", "--format", "json"]) == 1
    assert json.loads(capsys.readouterr().out)["gate"]["status"] == "block"
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(READY)))
    assert main(["review", "--issue", "-", "--profile", "offline", "--format", "markdown"]) == 0
    assert "1 work items" in capsys.readouterr().out


def test_cli_rejects_bad_issue_input(tmp_path, capsys):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    assert main(["review", "--issue", str(p), "--profile", "offline"]) == 2
    assert main(["review", "--issue", str(p), "--diff", "x.patch", "--profile", "offline"]) == 2
    assert "cannot read issue" in capsys.readouterr().err


def test_refinement_prompt_reaches_the_model(runtime):
    result = _review(READY, profile="balanced")
    routed = {s for r in result["run"]["routing"] for s in r["skills"]}
    assert "refinement.issue" in routed
    assert result["run"]["coverage"]["files"][0]["covered"]
