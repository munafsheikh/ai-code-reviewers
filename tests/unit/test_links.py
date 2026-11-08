"""Every review comment and finding links to its evidence so reviews can be documented."""

import json

from orchestrator import __version__
from orchestrator.engine import links, report
from orchestrator.engine.review import run_review
from tests.conftest import fixture_diff

REPO, REV = "https://github.com/acme/app", "0123456789abcdef0123456789abcdef01234567"


def test_location_and_commit_permalinks():
    assert links.location_url(REPO, REV, "src/A.java", 10, 12) == f"{REPO}/blob/{REV}/src/A.java#L10-L12"
    assert links.location_url(REPO + ".git", REV, "a.py", 3, 3) == f"{REPO}/blob/{REV}/a.py#L3"
    assert links.commit_url(REPO, REV) == f"{REPO}/commit/{REV}"
    # Unknown or non-web repository: no fabricated link.
    assert links.location_url(None, REV, "a.py", 1, 1) is None
    assert links.location_url("git@github.com:acme/app.git", REV, "a.py", 1, 1) is None
    assert links.location_url(REPO, None, "a.py", 1, 1) is None


def test_rule_links_point_at_versioned_anchors(monkeypatch):
    assert links.rule_url("INJ-001", "security.injection", "0.2.0").endswith("/blob/v0.2.0/docs/generated/rules.md#inj-001")
    assert links.rule_url("model.lang.java.core", "lang.java.core", "0.2.0").endswith("rules.md#skill-lang-java-core")
    monkeypatch.setenv("ACR_DOCS_BASE", "https://docs.internal/acr")
    assert links.rule_url("ERR-001", "x", "9.9.9") == "https://docs.internal/acr/rules.md#err-001"


def test_review_result_and_renderers_carry_links(monkeypatch):
    monkeypatch.setenv("ACR_RUN_URL", "https://github.com/acme/app/actions/runs/42")
    r = run_review(fixture_diff("java-leak-injection"), "offline", revision=REV, repository=REPO)
    assert r["run"]["links"]["commit"] == f"{REPO}/commit/{REV}"
    assert r["run"]["links"]["ci_run"].endswith("/runs/42")
    inj = next(f for f in r["findings"] if f["rule_id"] == "INJ-001")
    assert inj["links"]["location"] == f"{REPO}/blob/{REV}/src/main/java/app/UserDao.java#L10"
    assert inj["links"]["rule"].endswith(f"/v{__version__}/docs/generated/rules.md#inj-001")

    md = report.to_markdown(r)
    assert f"commit [`{REV[:7]}`]({REPO}/commit/{REV})" in md
    assert "[CI run](https://github.com/acme/app/actions/runs/42)" in md
    assert f"]({REPO}/blob/{REV}/src/main/java/app/UserDao.java#L10)" in md
    assert "[`INJ-001`](" in md

    sarif = json.loads(report.to_sarif(r))
    rules = {x["id"]: x for x in sarif["runs"][0]["tool"]["driver"]["rules"]}
    assert rules["INJ-001"]["helpUri"].endswith("rules.md#inj-001")


def test_without_repository_links_are_omitted_not_broken():
    r = run_review(fixture_diff("python-unsafe"), "offline")
    assert r["run"]["links"]["commit"] is None and r["run"]["links"]["ci_run"] is None
    assert all(f["links"]["location"] is None for f in r["findings"])
    md = report.to_markdown(r)
    assert "](None)" not in md and "/blob/None" not in md


def test_every_rule_and_skill_has_an_anchor_in_the_reference():
    from orchestrator import config as cfg
    from orchestrator.cli import docsgen

    doc = docsgen.rules_md()
    for s in cfg.load_skills().values():
        assert f'<a id="{links.skill_anchor(s.id)}"></a>' in doc
        for rule in s.rules:
            assert f'<a id="{links.rule_anchor(rule["id"])}"></a>' in doc


def test_markdown_reports_what_the_model_contributed(runtime, monkeypatch):
    fake = {
        "findings": [
            {"path": "svc/jobs.py", "line": 9, "severity": "critical", "title": "Shell injection"},
            {"path": "/etc/passwd", "line": 1, "severity": "critical", "title": "invented"},
        ]
    }
    monkeypatch.setenv("FAKE_RESPONSE_TEXT", json.dumps(fake))
    md = report.to_markdown(run_review(fixture_diff("python-unsafe"), "balanced"))
    assert "Model output: 2 findings returned, 1 accepted, 1 discarded" in md
