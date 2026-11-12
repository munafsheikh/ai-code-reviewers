"""Workflow and action files must be valid YAML: GitHub silently drops an unparsable
workflow's triggers (e.g. workflow_dispatch), which no other check would catch."""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]
FILES = sorted([*ROOT.glob(".github/workflows/*.yml"), *ROOT.glob(".github/workflows/*.yaml"), *ROOT.glob("integrations/**/action.yml")])


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_parses(path: Path) -> None:
    doc = yaml.safe_load(path.read_text())
    assert isinstance(doc, dict), "top level must be a mapping"
    if "workflows" in path.parts:
        assert isinstance(doc.get("name"), str), "workflow needs a name"
        assert True in doc or "on" in doc, "workflow needs triggers"  # YAML 1.1 reads `on` as True
    else:
        assert "runs" in doc, "action needs runs"


def test_found_files() -> None:
    assert any(p.name == "tag.yml" for p in FILES)
