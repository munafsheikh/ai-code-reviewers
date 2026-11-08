from orchestrator import config as cfg
from orchestrator.cli import validate
from orchestrator.engine import diff
from orchestrator.engine.rules import redact, run_rules


def _diff(path, *lines):
    body = "".join(f"+{line}\n" for line in lines)
    return diff.parse(f"--- a/{path}\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n{body}")


def test_every_rule_example_behaves_as_declared():
    r = validate.Report()
    validate.check_skills(cfg.home(), r)
    assert r.errors == []


def test_rules_only_scan_added_lines():
    d = diff.parse(
        '--- a/A.java\n+++ b/A.java\n@@ -1,2 +1,2 @@\n-String password = "hunter2hunter2";\n+String password = System.getenv("P");\n'
    )
    skills = cfg.load_skills()
    found = [f for s in skills.values() for f in run_rules(s, d)]
    assert found == []


def test_rule_findings_are_verified_only_at_high_confidence():
    skills = cfg.load_skills()
    files = _diff("A.java", 'String password = "hunter2hunter2";', "} catch (Exception e) {}")
    found = {f.rule_id: f for s in skills.values() for f in run_rules(s, files)}
    assert found["SEC-004"].kind == "hypothesis"  # medium confidence regex
    assert found["ERR-001"].kind == "verified"
    assert all(f.source == "rule" for f in found.values())


def test_block_scope_rule_spans_lines_and_reports_first_line():
    skills = cfg.load_skills()
    files = _diff("m.py", "try:", "    go()", "except OSError:", "    pass")
    (f,) = run_rules(skills["code-quality.error-handling"], files)
    assert (f.rule_id, f.location.start_line, f.location.end_line) == ("ERR-001", 3, 4)


def test_language_filter():
    skills = cfg.load_skills()
    assert run_rules(skills["lang.typescript.types"], _diff("a.py", "x: any = 1")) == []
    assert run_rules(skills["lang.typescript.types"], _diff("a.ts", "let x: any = 1"))


def test_redaction_never_echoes_full_secret():
    assert "hunter2hunter2" not in redact('password = "hunter2hunter2"')
    assert "Z7Q3XJ5M2N4P6R8T" not in redact("AKIAZ7Q3XJ5M2N4P6R8T")
    assert redact("ghp_" + "a" * 36).endswith("****")
