"""Outputs and manifests validate against the published schemas, using both validators."""

import json

import jsonschema
import pytest

from orchestrator import config as cfg
from orchestrator import schema
from orchestrator.engine import report
from orchestrator.engine.review import run_review
from tests.conftest import FIXTURES

CASES = sorted(p.name for p in FIXTURES.iterdir() if p.is_dir())


def test_schemas_are_valid_draft7():
    for f in schema.SCHEMAS.glob("*.json"):
        jsonschema.Draft7Validator.check_schema(json.loads(f.read_text()))


@pytest.mark.parametrize("case", CASES)
def test_results_validate(case):
    res = run_review((FIXTURES / case / "diff.patch").read_text(), "offline")
    s = schema.load("review-result")
    assert schema.validate(res, s) == []
    jsonschema.validate(res, s)
    sarif = json.loads(report.to_sarif(res))
    assert sarif["version"] == "2.1.0" and isinstance(sarif["runs"][0]["results"], list)


def test_mini_validator_agrees_with_reference_on_invalid_input():
    s = schema.load("finding")
    bad = {"rule_id": "x", "severity": "huge"}
    ours = schema.validate(bad, s)
    ref = list(jsonschema.Draft7Validator(s).iter_errors(bad))
    assert ours and ref


@pytest.mark.parametrize(
    "kind,glob,name",
    [
        ("skill", "skills/**/skill.toml", "skill"),
        ("model", "models/registry/*.toml", "model"),
        ("wrapper", "wrappers/**/wrapper.toml", "wrapper"),
    ],
)
def test_manifests_validate_with_reference(kind, glob, name):
    s = schema.load(name)
    files = list(cfg.home().glob(glob))
    assert files
    for f in files:
        jsonschema.validate(cfg.load_toml(f), s)


def test_profiles_validate_with_reference():
    s = schema.load("profile")
    for d in (cfg.home() / "profiles").iterdir():
        jsonschema.validate(cfg.load_profile(d.name), s)
