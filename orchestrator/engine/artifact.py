"""Lifecycle artifacts: non-code work items reviewed by the same rules, models and gate as diffs.

An artifact (today: a GitHub issue) is rendered to text and presented to the engine as one
newly added file at a virtual path such as ``@issue/42``. Every line counts as added, so line
rules, expectations, model prompts, output validation, coverage and the gate apply unchanged.
Virtual paths start with ``@`` so they can never collide with a repository file.
"""

from __future__ import annotations

import re
from typing import Any

PREFIX = "@"
ISSUE_PREFIX = "@issue/"
# Stage category that must examine each artifact kind for it to count as covered.
STAGE_FOR_PREFIX = {ISSUE_PREFIX: "refinement"}

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")


def is_artifact(path: str) -> bool:
    return path.startswith(PREFIX)


def stage_for(path: str) -> str | None:
    return next((s for p, s in STAGE_FOR_PREFIX.items() if path.startswith(p)), None)


def _labels(raw: Any) -> list[str]:
    out = []
    for item in raw or []:
        name = item.get("name") if isinstance(item, dict) else item
        if isinstance(name, str) and name.strip():
            out.append(name.strip())
    return out


def render_github_issue(data: dict[str, Any]) -> tuple[str, str]:
    """Return (virtual path, text) for a GitHub issue.

    Accepts ``gh issue view N --json number,title,body,labels,url``, a REST API issue object,
    or an ``issues`` webhook payload (``{"issue": {...}}``).
    """
    issue = data.get("issue", data) if isinstance(data, dict) else None
    if not isinstance(issue, dict) or "number" not in issue or "title" not in issue:
        raise ValueError("not a GitHub issue: expected an object with `number` and `title`")
    number = int(issue["number"])
    url = issue.get("url") or ""
    if isinstance(url, str) and url.startswith("https://api.github.com/"):
        url = issue.get("html_url") or url
    head = [f"# {' '.join(str(issue['title']).split())}"]
    labels = _labels(issue.get("labels"))
    if labels:
        head.append(f"Labels: {', '.join(labels)}")
    if url:
        head.append(f"Issue: {url}")
    body = (issue.get("body") or "").replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    text = "\n".join(head) + "\n\n" + body + "\n"
    return f"{ISSUE_PREFIX}{number}", text


def to_diff(path: str, text: str) -> str:
    """A unified diff that adds ``text`` as a new file at ``path``."""
    lines = text.splitlines() or [""]
    return f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n" + "".join(f"+{line}\n" for line in lines)


def issue_diff(data: dict[str, Any]) -> str:
    return to_diff(*render_github_issue(data))


def anchor(added: list[tuple[int, str]], line: int) -> str | None:
    """Nearest heading at or above ``line``: where a finding sits inside the artifact."""
    found = None
    for n, text in added:
        if n > line:
            break
        m = _HEADING.match(text)
        if m:
            found = m.group(1)
    return found


def web_url(repository: str | None, path: str) -> str | None:
    """Link to the artifact itself (issues are not files at a revision)."""
    if not repository or not repository.startswith(("https://", "http://")) or not path.startswith(ISSUE_PREFIX):
        return None
    return f"{repository.removesuffix('.git').rstrip('/')}/issues/{path.removeprefix(ISSUE_PREFIX)}"
