"""Fail on broken relative links and anchors in Markdown files (no network)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
SKIP = ("http://", "https://", "mailto:", "#")


def anchors(md: Path) -> set[str]:
    out = set()
    for line in md.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            slug = re.sub(r"[^\w\- ]", "", line.lstrip("#").strip().lower()).replace(" ", "-")
            out.add(slug)
    return out


def main() -> int:
    errors = []
    files = [p for p in ROOT.rglob("*.md") if not any(x in p.parts for x in (".git", ".venv", "node_modules", "out"))]
    for md in files:
        text = md.read_text(encoding="utf-8")
        text = re.sub(r"```.*?```", "", text, flags=re.S)
        for target in LINK.findall(text):
            if target.startswith(SKIP):
                continue
            path, _, frag = target.partition("#")
            dest = (md.parent / path).resolve()
            if not dest.exists():
                errors.append(f"{md.relative_to(ROOT)}: broken link -> {target}")
            elif frag and dest.suffix == ".md" and frag not in anchors(dest):
                errors.append(f"{md.relative_to(ROOT)}: missing anchor -> {target}")
    for e in errors:
        print(e)
    print(f"links: {len(files)} files checked, {len(errors)} broken")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
