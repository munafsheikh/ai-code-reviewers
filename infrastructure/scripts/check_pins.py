"""Supply-chain check: third-party actions pinned by commit SHA, container images by digest."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
USES = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)")
IMAGE = re.compile(
    r"(?:image:|FROM|=|docker run[^\n]*?)\s*((?:[\w.-]+/)+[\w.-]+:[\w.-]+(?:@sha256:[0-9a-f]{64})?|python:[\w.-]+(?:@sha256:[0-9a-f]{64})?)"
)
ALLOW_UNPINNED_IMAGES = {"alpine/git:latest"}  # consumer template placeholder, documented in the file


def main() -> int:
    errors = []
    for f in [*ROOT.glob(".github/workflows/*.yml"), *ROOT.glob("integrations/**/*.yml")]:
        for n, line in enumerate(f.read_text().splitlines(), 1):
            m = USES.match(line)
            if m:
                ref = m.group(1)
                if ref.startswith("./") or ref.startswith("docker://"):
                    continue
                # Consumer templates reference this project's own release tags; its workflows pin SHAs.
                if f.parts[len(ROOT.parts)] == "integrations" and re.fullmatch(
                    r"munafsheikh/ai-code-reviewers/[\w/.-]+@v\d+\.\d+\.\d+", ref
                ):
                    continue
                if not re.search(r"@[0-9a-f]{40}$", ref):
                    errors.append(f"{f.relative_to(ROOT)}:{n}: action not pinned by SHA: {ref}")
    for f in [
        ROOT / "compose.yaml",
        *ROOT.glob("infrastructure/**/Dockerfile"),
        *ROOT.glob("infrastructure/scripts/*.sh"),
        *ROOT.glob(".github/workflows/*.yml"),
        *ROOT.glob("integrations/**/*.yml"),
    ]:
        for n, line in enumerate(f.read_text().splitlines(), 1):
            for img in IMAGE.findall(line):
                if img.rsplit(":", 1)[-1] in ("ro", "rw") or img.startswith((".", "var/")):
                    continue  # volume mount, not an image
                if "@sha256:" not in img and img not in ALLOW_UNPINNED_IMAGES and not img.startswith(("acr-", "ghcr.io/munafsheikh/")):
                    errors.append(f"{f.relative_to(ROOT)}:{n}: image not pinned by digest: {img}")
    for e in errors:
        print(e)
    print(f"pins: {len(errors)} unpinned references")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
