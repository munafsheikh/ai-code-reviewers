from orchestrator import config as cfg
from orchestrator.engine import coverage, diff, gate
from orchestrator.engine.review import run_review


def _files(*paths):
    return diff.parse("".join(f"--- a/{p}\n+++ b/{p}\n@@ -0,0 +1 @@\n+x = 1\n" for p in paths))


def _skills(*patterns):
    return cfg.select_skills(list(patterns), cfg.load_skills())


def test_docs_need_a_documentation_check_and_code_needs_a_code_check():
    cov = coverage.compute(_skills("*"), _files("README.md", "docs/a.md", "src/app.py", "deploy/Dockerfile"), set())
    rows = {r["path"]: r for r in cov["files"]}
    assert rows["README.md"]["kind"] == "docs" and "documentation" in rows["README.md"]["categories"]
    assert rows["src/app.py"]["kind"] == "code" and "security" in rows["src/app.py"]["categories"]
    assert cov["uncovered"] == []
    assert cov["by_kind"] == {"code": 2, "docs": 2}


def test_profile_without_documentation_skills_leaves_docs_uncovered():
    cov = coverage.compute(_skills("security.*", "maintainability.*"), _files("README.md", "src/app.py"), set())
    assert cov["uncovered"] == ["README.md"]


def test_prompt_only_skill_counts_only_when_its_model_ran():
    files = _files("src/app.py")
    assert coverage.compute(_skills("architecture.*"), files, set())["uncovered"] == ["src/app.py"]
    assert coverage.compute(_skills("architecture.*"), files, {"architecture.design"})["uncovered"] == []


def test_gate_blocks_on_uncovered_files_only_when_policy_requires_it():
    lax = gate.evaluate([], {"gate": {}}, [], ["README.md"])
    strict = gate.evaluate([], {"gate": {"require_coverage": True}}, [], ["README.md", "a.py"])
    assert (lax["status"], lax["uncovered_files"]) == ("pass", 0)
    assert strict["status"] == "block" and strict["exit_code"] == 1
    assert strict["reasons"] == ["no documentation review coverage for README.md", "no code review coverage for a.py"]


def test_review_result_reports_coverage_for_code_and_docs():
    d = "--- a/README.md\n+++ b/README.md\n@@ -0,0 +1 @@\n+Install: TBD\n--- a/m.py\n+++ b/m.py\n@@ -0,0 +1 @@\n+x = 1\n"
    result = run_review(d, profile_name="offline")
    cov = result["run"]["coverage"]
    assert cov["by_kind"] == {"code": 1, "docs": 1} and cov["uncovered"] == []
    assert {f["rule_id"] for f in result["findings"]} >= {"DOC-101"}
    assert result["gate"]["status"] == "block"
