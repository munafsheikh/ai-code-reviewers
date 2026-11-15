"""Release automation: version planning, applying and checking (infrastructure/scripts/release.py)."""

import importlib.util
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("release", ROOT / "infrastructure/scripts/release.py")
rel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rel)

CHANGELOG = "# Changelog\n\n## [Unreleased]\n\n{body}\n## [1.4.2] - 2026-01-01\n\n### Fixed\n- old\n"


def _repo(tmp_path: Path, body: str, version: str = "1.4.2") -> Path:
    (tmp_path / "orchestrator").mkdir()
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "x"\nversion = "{version}"\n')
    (tmp_path / "orchestrator/__init__.py").write_text(f'__version__ = "{version}"\n')
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG.format(body=body))
    gh = tmp_path / "integrations/github"
    gh.mkdir(parents=True)
    (gh / "README.md").write_text(
        f"uses: munafsheikh/ai-code-reviewers/integrations/github@v{version}\nimage ghcr.io/munafsheikh/ai-code-reviewers:{version}\n"
    )
    return tmp_path


@pytest.mark.parametrize(
    ("body", "bump", "nxt"),
    [
        ("", "none", None),
        ("### Fixed\n- a\n", "patch", "1.4.3"),
        ("### Security\n- a\n", "patch", "1.4.3"),
        ("### Added\n- a\n### Fixed\n- b\n", "minor", "1.5.0"),
        ("### Changed\n- a\n", "minor", "1.5.0"),
        ("### Removed\n- a\n", "major", "2.0.0"),
        ("### Changed\n- BREAKING: renamed flag\n", "major", "2.0.0"),
    ],
)
def test_plan_follows_the_changelog(tmp_path, body, bump, nxt):
    p = rel.plan(_repo(tmp_path, body), [])
    assert (p["bump"], p["next"], p["current"]) == (bump, nxt, "1.4.2")


def test_breaking_change_bumps_minor_while_0x(tmp_path):
    assert rel.plan(_repo(tmp_path, "### Removed\n- a\n", "0.2.0"), [])["next"] == "0.3.0"


def test_pr_labels_override_and_skip_wins(tmp_path):
    root = _repo(tmp_path, "### Fixed\n- a\n")
    assert rel.plan(root, ["bug", "release:minor"])["next"] == "1.5.0"
    assert rel.plan(root, ["release:major", "release:skip"])["next"] is None
    assert rel.plan(root, ["unrelated"])["next"] == "1.4.3"


def test_apply_rewrites_every_reference_and_check_agrees(tmp_path):
    root = _repo(tmp_path, "### Fixed\n- a\n")
    changed = rel.apply(root, "1.4.3", "2026-11-15")
    assert set(changed) == {"pyproject.toml", "orchestrator/__init__.py", "CHANGELOG.md", "integrations/github/README.md"}
    assert rel.check(root, "1.4.3") == []
    assert "## [Unreleased]\n\n## [1.4.3] - 2026-11-15\n\n### Fixed\n- a" in (root / "CHANGELOG.md").read_text()
    assert rel.notes(root, "1.4.3") == "### Fixed\n- a\n"
    assert rel.plan(root, [])["next"] is None  # nothing left to release


def test_check_reports_drift(tmp_path):
    root = _repo(tmp_path, "")
    (root / "orchestrator/__init__.py").write_text('__version__ = "9.9.9"\n')
    errors = rel.check(root, "1.4.2")
    assert any("orchestrator/__init__.py" in e for e in errors)


def test_apply_refuses_an_existing_section(tmp_path):
    with pytest.raises(SystemExit):
        rel.apply(_repo(tmp_path, "### Fixed\n- a\n"), "1.4.2", "2026-11-15")


def test_image_tags():
    assert rel.image_tags("v0.3.0", "a" * 40, "MunafSheikh") == {
        "namespace": "munafsheikh",
        "revision": "a" * 40,
        "version": "0.3.0",
        "tags": "0.3.0 0.3 latest",
    }
    assert rel.image_tags("", "0123456789abcdef", "ns")["tags"] == "edge sha-0123456789ab"
    for bad in (("1.2", "a" * 40, "ns"), ("", "not-a-sha", "ns"), ("", "a" * 40, "bad ns")):
        with pytest.raises(SystemExit):
            rel.image_tags(*bad)


def test_repository_versions_are_consistent():
    """The real repository: every pinned reference agrees with pyproject."""
    assert rel.check(ROOT, rel.current_version(ROOT)) == []


def test_apply_on_a_copy_of_the_repository(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(".git", "out", ".acr-cache", "__pycache__"))
    nxt = rel.plan(root, ["release:patch"])["next"]
    rel.apply(root, nxt, "2026-11-15")
    assert rel.check(root, nxt) == []
