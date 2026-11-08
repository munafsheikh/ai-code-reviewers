"""Review coverage: which check categories actually examined each changed file.

A file counts as covered by a skill only when that skill can produce a finding for it in
this run: a deterministic rule or companion applies to it, or its prompt was routed to a
model that is available. Documentation files need a `documentation` check; every other
file needs at least one code check (any other category). Files that get neither are
reported, and a policy with ``require_coverage`` blocks on them.
"""

from __future__ import annotations

from orchestrator.config import Skill
from orchestrator.engine.diff import FileDiff
from orchestrator.engine.rules import glob_hit, rule_applies

DOC_GLOBS = ("*.md", "*.markdown", "*.rst", "*.adoc", "docs/*", "doc/*")
DOC_CATEGORY = "documentation"


def is_doc(path: str) -> bool:
    return glob_hit(path, list(DOC_GLOBS))


def covers(skill: Skill, f: FileDiff, model_backed: bool) -> bool:
    # Companions trigger on their own `when` globs, independent of the skill's languages.
    if any(f.matches(skill.file_globs, ["*"], skill.exclude_globs) and glob_hit(f.path, c["when"]) for c in skill.companions):
        return True
    if not f.matches(skill.file_globs, skill.languages, skill.exclude_globs):
        return False
    return (model_backed and bool(skill.prompt)) or any(rule_applies(r, f) for r in skill.rules)


def compute(skills: list[Skill], files: list[FileDiff], model_backed: set[str]) -> dict:
    """``model_backed``: ids of skills whose prompt reached an available model in this run."""
    rows, by_category = [], {}
    for f in files:
        cats = sorted({s.category for s in skills if covers(s, f, s.id in model_backed)})
        kind = "docs" if is_doc(f.path) else "code"
        ok = DOC_CATEGORY in cats if kind == "docs" else any(c != DOC_CATEGORY for c in cats)
        rows.append({"path": f.path, "kind": kind, "categories": cats, "covered": ok})
        for c in cats:
            by_category[c] = by_category.get(c, 0) + 1
    return {
        "files": rows,
        "by_category": dict(sorted(by_category.items())),
        "by_kind": {k: sum(1 for r in rows if r["kind"] == k) for k in ("code", "docs")},
        "uncovered": [r["path"] for r in rows if not r["covered"]],
    }
