import pytest

from orchestrator import config as cfg
from orchestrator.cli import validate
from orchestrator.engine import analyzers, diff
from orchestrator.engine.rules import run_rules


def _diff(path, *lines):
    body = "".join(f"+{line}\n" for line in lines)
    return diff.parse(f"--- a/{path}\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n{body}")


def _found(path, *lines):
    skills = cfg.load_skills()
    return [f for s in skills.values() for f in run_rules(s, _diff(path, *lines))]


# --- analyzers in isolation ----------------------------------------------------------------
@pytest.mark.parametrize(
    ("lines", "idx", "want"),
    [
        (["r = requests.get(url)"], 0, True),
        (["r = requests.get(url, timeout=5).json()"], 0, False),  # chained call: inspects get(), not json()
        (["resp = requests.post(", "    url,", "    json=body,", ")"], 0, True),
        (["resp = requests.post(", "    url,", "    timeout=(3, 27),", ")"], 0, False),
        (["return requests.request(m, u, **kwargs)"], 0, False),  # **kwargs may carry timeout
        (["        r = httpx.get(url)", "        return r"], 0, True),  # indented body still parses
        (["session.get(url)"], 0, False),  # a Session may carry a default timeout
        (["r = requests.get(url,"], 0, None),  # truncated: undecidable
    ],
)
def test_http_without_timeout(lines, idx, want):
    assert analyzers.python_http_without_timeout(lines, idx) is want


@pytest.mark.parametrize(
    ("lines", "idx", "want"),
    [
        (["cur.execute(f\"SELECT * FROM u WHERE n = '{n}'\")"], 0, True),
        (['cur.execute("SELECT * FROM o WHERE c = %s" % cid)'], 0, True),
        (['cur.execute("DELETE FROM " + table)'], 0, True),
        (["cur.execute(\"SELECT 1 FROM t WHERE x LIKE '{}%'\".format(term))"], 0, True),
        (["q = f\"SELECT * FROM j WHERE s = '{s}'\"", "cur.execute(q)"], 1, True),  # follows local assignment
        (['cur.execute("SELECT * FROM u WHERE n = %s", (n,))'], 0, False),
        (['cur.execute("CREATE TABLE t (id INT)")'], 0, False),
        (["pool.execute(fn, items)"], 0, False),
        (['cur.execute("SELECT * FROM t" +'], 0, None),
    ],
)
def test_sql_built_string(lines, idx, want):
    assert analyzers.python_sql_built_string(lines, idx) is want


@pytest.mark.parametrize(
    ("line", "want"),
    [
        ("cp $SRC /backup/", True),
        ("if [ -f $CONFIG ]; then", True),
        ('mv "$tmp" $OUT/report.csv', True),
        ("x=$((a + $b)) && rm $f", True),
        ('cp "$SRC" /backup/', False),
        ("if [[ -f $CONFIG ]]; then", False),
        ("name=$USER_NAME", False),
        ("count=$((count + $step))", False),
        ("case $MODE in", False),
        ('echo "hello $name"', False),
        ("echo $((1 + 2))", False),
        ("exit $?", False),
        ("# rm $old", False),
        ('echo "unbalanced $x', None),
    ],
)
def test_shell_unquoted_expansion(line, want):
    assert analyzers.shell_unquoted_expansion([line], 0) is want


def test_unknown_analyzer_is_named():
    with pytest.raises(KeyError, match="known:"):
        analyzers.get("nope")


# --- wired into the rule engine ------------------------------------------------------------
def test_confirmed_candidate_is_reported_as_verified():
    (f,) = [f for f in _found("svc/a.py", "rates = requests.get(URL).json()") if f.rule_id == "PY-007"]
    assert f.confidence == "high" and f.kind == "verified"


def test_rejected_candidate_is_dropped():
    found = _found("svc/a.py", "resp = requests.post(", "    url,", "    timeout=10,", ")")
    assert "PY-007" not in {f.rule_id for f in found}


def test_undecidable_candidate_follows_fallback():
    # PY-007 keeps an undecidable candidate at its own confidence; INJ-006 drops it.
    found = {f.rule_id: f for f in _found("svc/a.py", "r = requests.get(url,", 'cur.execute("SELECT " +')}
    assert found["PY-007"].confidence == "low"
    assert "INJ-006" not in found


def test_inj006_defers_to_inj001_so_a_line_is_reported_once():
    ids = [f.rule_id for f in _found("svc/a.py", 'cur.execute(f"SELECT * FROM t WHERE id = {uid}")')]
    assert ids.count("INJ-001") == 1 and "INJ-006" not in ids


def test_shell_rules_apply_only_to_shell_files():
    assert {f.rule_id for f in _found("deploy.sh", "cp $SRC /backup/")} == {"SH-001"}
    assert not [f for f in _found("deploy.py", "cp $SRC /backup/") if f.rule_id.startswith("SH-")]


def test_validate_rejects_unknown_analyzer(tmp_path, monkeypatch):
    skill = tmp_path / "skills" / "x"
    skill.mkdir(parents=True)
    (skill / "skill.toml").write_text(
        'id = "x.y"\nversion = "1.0.0"\ninterface = "acr.skill/v1"\ncategory = "code-quality"\n'
        'description = "d"\nlanguages = ["python"]\nfile_globs = ["*.py"]\ntier = "none"\n\n'
        '[[rules]]\nid = "XX-001"\ntitle = "t"\nseverity = "minor"\nconfidence = "low"\n'
        'pattern = "x"\nanalyzer = "missing"\nexplanation = "e"\nremediation = "r"\n'
        'examples.match = ["x"]\nexamples.no_match = ["y"]\n'
    )
    r = validate.Report()
    validate.check_skills(tmp_path, r)
    assert any("unknown analyzer 'missing'" in e for e in r.errors)
