import json

import pytest

from orchestrator import config as cfg
from orchestrator.engine import diff, parse

D = diff.parse('--- a/A.java\n+++ b/A.java\n@@ -1,1 +1,3 @@\n x\n+String q = "SELECT" + id;\n+foo();\n')
SKILLS = [cfg.load_skills()["security.injection"], cfg.load_skills()["code-quality.error-handling"]]


def _f(**kw):
    base = {
        "path": "A.java",
        "line": 2,
        "severity": "critical",
        "title": "SQL injection",
        "explanation": "x",
        "evidence": "q",
        "remediation": "bind",
        "confidence": "high",
    }
    return {**base, **kw}


@pytest.mark.parametrize(
    "text",
    [
        json.dumps({"findings": [_f()]}),
        "Sure! Here you go:\n```json\n" + json.dumps({"findings": [_f()]}) + "\n```",
        "prefix " + json.dumps([_f()]) + " suffix",
    ],
)
def test_extracts_json_in_common_shapes(text):
    found, stats = parse.to_findings(text, SKILLS, D, "m")
    assert len(found) == 1 and stats["accepted"] == 1
    assert found[0].source == "model" and found[0].kind == "hypothesis"
    assert found[0].skill == "security.injection"  # inferred from title


def test_hallucinated_file_is_discarded():
    found, stats = parse.to_findings(json.dumps({"findings": [_f(path="Nope.java")]}), SKILLS, D, "m")
    assert found == [] and stats["discarded"] == 1


def test_line_outside_hunk_is_kept_but_marked_unverified_low_confidence():
    (f,), stats = parse.to_findings(json.dumps({"findings": [_f(line=99)]}), SKILLS, D, "m")
    assert f.location.verified is False and f.confidence == "low" and stats["unverified_location"] == 1


def test_severity_aliases_and_invalid_items():
    items = [_f(severity="HIGH"), _f(severity="bogus"), _f(title=""), "not a dict"]
    found, stats = parse.to_findings(json.dumps({"findings": items}), SKILLS, D, "m")
    assert [f.severity for f in found] == ["major"] and stats["discarded"] == 3


def test_unparseable_output_yields_no_findings_and_records_error():
    found, stats = parse.to_findings("I refuse.", SKILLS, D, "m")
    assert found == [] and stats["parse_error"]


@pytest.mark.parametrize(
    "text,sev",
    [
        ("SEVERITY: NONE", "NONE"),
        ("SEVERITY: MINOR", "MINOR"),
        ("SEVERITY: BLOCK", "BLOCK"),
        ("severity: block", "BLOCK"),
        ("  SEVERITY: **BLOCK**", "BLOCK"),
        ("no header", "NONE"),
        ("SEVERITY: HIGH", "NONE"),
        ("SEVERITY: MINOR\nSEVERITY: BLOCK", "MINOR"),
    ],
)
def test_legacy_severity_matches_reviewgate(text, sev):
    assert parse.legacy_severity(text) == sev
