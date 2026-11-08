from orchestrator import config as cfg
from orchestrator.cli import validate
from orchestrator.engine import diff
from orchestrator.engine.rules import redact, run_companions, run_rules


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


def _multi(*files):
    """files: (path, line) pairs -> one diff, each file with one added line."""
    return diff.parse("".join(f"--- a/{p}\n+++ b/{p}\n@@ -0,0 +1 @@\n+{line}\n" for p, line in files))


def _companions(files):
    return [f for s in cfg.load_skills().values() for f in run_companions(s, files)]


def test_companion_fires_once_per_diff_on_first_trigger_without_docs():
    found = _companions(_multi(("Dockerfile", "RUN make"), (".github/workflows/x.yml", "  build:"), ("src/a.py", "x = 1")))
    (f,) = [f for f in found if f.rule_id == "DOC-001"]
    assert (f.location.path, f.location.start_line, f.kind, f.severity) == ("Dockerfile", 1, "hypothesis", "major")
    assert "Dockerfile" in f.evidence and ".github/workflows/x.yml" in f.evidence


def test_any_docs_change_in_the_diff_satisfies_companions():
    files = _multi(("Dockerfile", "RUN make"), ("src/a.py", 'v = os.getenv("X")'), ("CHANGELOG.md", "- note"))
    assert _companions(files) == []


def test_pattern_companion_reports_matching_line_and_skips_tests():
    files = diff.parse('--- a/m.py\n+++ b/m.py\n@@ -0,0 +1,2 @@\n+a = 1\n+b = os.environ.get("ACR_X")\n')
    (f,) = _companions(files)
    assert (f.rule_id, f.location.start_line) == ("DOC-003", 2)
    assert _companions(_multi(("tests/unit/test_m.py", 'b = os.environ.get("ACR_X")'))) == []


def test_pin_bumps_do_not_require_docs():
    files = _multi(
        (".github/workflows/ci.yml", "      - uses: actions/checkout@" + "a" * 40), ("Dockerfile", "FROM python:3.13@sha256:" + "b" * 64)
    )
    assert _companions(files) == []


def test_companion_examples_are_enforced(tmp_path):
    skill = tmp_path / "skills" / "x" / "skill.toml"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        'id = "x.y"\nversion = "1.0.0"\ninterface = "acr.skill/v1"\ncategory = "maintainability"\ndescription = ""\ntier = "none"\n'
        '[[companions]]\nid = "DOC-999"\ntitle = "t"\nseverity = "minor"\nconfidence = "low"\nwhen = ["*.proto"]\nrequires = ["*.md"]\n'
        'explanation = "e"\nremediation = "r"\nexamples.flag = [{files = ["a.proto", "README.md"]}]\nexamples.pass = [{files = ["a.py"]}]\n'
    )
    r = validate.Report()
    validate.check_skills(tmp_path, r)
    assert r.errors == ["skills/x/skill.toml: companion DOC-999 should fire for example {'files': ['a.proto', 'README.md']}"]
