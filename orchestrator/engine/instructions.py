"""Operator review instructions: team guidance added to every model review at run time.

Sources, in order (all optional, all combined):
  1. ``*.md`` / ``*.txt`` files in ``$ACR_INSTRUCTIONS_DIR`` (default ``/etc/acr/instructions.d``),
     sorted by name; ``README*`` files are ignored. Bake them into an image
     (``COPY team.md /etc/acr/instructions.d/``) or mount them with Compose.
  2. ``--instructions FILE`` (repeatable) on ``acr review``.
  3. ``$ACR_INSTRUCTIONS``: inline text, e.g. set by a CI job.

Instructions come from whoever configures the review (trusted), unlike the diff (untrusted):
they are placed in the system prompt, outside the data fence, and can never override the
security rules. Deterministic rules ignore them. Each source is recorded in the result by
name, size and SHA-256 so a review can be traced to the exact guidance it used.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DIR = "/etc/acr/instructions.d"
MAX_CHARS = 8000
SUFFIXES = (".md", ".txt")


@dataclass
class Instructions:
    text: str = ""
    sources: list[dict] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.text.strip())


def _part(source: str, body: str) -> tuple[str, dict]:
    body = body.strip()
    return body, {"source": source, "chars": len(body), "sha256": hashlib.sha256(body.encode()).hexdigest()}


def load(files: list[str] | None = None, env: dict[str, str] | None = None) -> Instructions:
    env = os.environ if env is None else env
    parts: list[tuple[str, dict]] = []
    d = Path(env.get("ACR_INSTRUCTIONS_DIR") or DEFAULT_DIR)
    if d.is_dir():
        for p in sorted(d.iterdir()):
            if p.is_file() and p.suffix.lower() in SUFFIXES and not p.name.lower().startswith("readme"):
                parts.append(_part(str(p), p.read_text(encoding="utf-8")))
    for f in files or []:
        parts.append(_part(f, Path(f).read_text(encoding="utf-8")))
    if env.get("ACR_INSTRUCTIONS", "").strip():
        parts.append(_part("$ACR_INSTRUCTIONS", env["ACR_INSTRUCTIONS"]))
    parts = [(b, meta) for b, meta in parts if b]
    text = "\n\n".join(b for b, _ in parts)
    sources = [meta for _, meta in parts]
    if len(text) > MAX_CHARS:  # bounded: instructions must not crowd out the diff
        text = text[:MAX_CHARS] + "\n[instructions truncated]"
        for s in sources:
            s["truncated"] = True
    return Instructions(text=text, sources=sources)
