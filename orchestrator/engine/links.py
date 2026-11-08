"""Stable links that make every review traceable and citable.

- location: permalink to the exact lines at the reviewed revision (GitHub/GitLab/Gitea-style
  `<repo>/blob/<rev>/<path>#L<a>-L<b>`), when the repository URI and revision are known
- rule: the rule's documentation at the released version of this tool
- commit / ci_run: the reviewed commit and the CI run that produced the review (ACR_RUN_URL)

ACR_DOCS_BASE overrides where rule documentation lives (e.g. an internal mirror).
"""

from __future__ import annotations

import os
import re

PROJECT = "https://github.com/munafsheikh/ai-code-reviewers"


def docs_base(version: str) -> str:
    return os.environ.get("ACR_DOCS_BASE") or f"{PROJECT}/blob/v{version}/docs/generated"


def rule_anchor(rule_id: str) -> str:
    return rule_id.lower()


def skill_anchor(skill_id: str) -> str:
    return "skill-" + re.sub(r"[^a-z0-9]+", "-", skill_id.lower()).strip("-")


def rule_url(rule_id: str, skill: str, version: str) -> str:
    anchor = skill_anchor(skill) if rule_id.startswith("model.") else rule_anchor(rule_id)
    return f"{docs_base(version)}/rules.md#{anchor}"


def _web_repo(repository: str | None) -> str | None:
    if not repository or not repository.startswith(("https://", "http://")):
        return None
    return repository.removesuffix(".git").rstrip("/")


def commit_url(repository: str | None, revision: str | None) -> str | None:
    repo = _web_repo(repository)
    return f"{repo}/commit/{revision}" if repo and revision else None


def location_url(repository: str | None, revision: str | None, path: str, start: int, end: int | None) -> str | None:
    repo = _web_repo(repository)
    if not repo or not revision:
        return None
    lines = f"L{start}" + (f"-L{end}" if end and end > start else "")
    return f"{repo}/blob/{revision}/{path}#{lines}"


def ci_run_url() -> str | None:
    return os.environ.get("ACR_RUN_URL") or None
