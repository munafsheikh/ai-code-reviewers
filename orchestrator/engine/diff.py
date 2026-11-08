"""Unified-diff parsing: files, hunks and added lines with new-file line numbers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import PurePosixPath

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

LANGUAGES = {
    ".java": "java",
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".kt": "kotlin",
    ".go": "go",
    ".cs": "csharp",
    ".rb": "ruby",
    ".sh": "shell",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".tf": "terraform",
}


@dataclass
class FileDiff:
    path: str
    text: str = ""
    added: list[tuple[int, str]] = field(default_factory=list)
    deleted: bool = False
    binary: bool = False

    @property
    def language(self) -> str:
        return LANGUAGES.get(PurePosixPath(self.path).suffix.lower(), "other")

    @property
    def changed_lines(self) -> set[int]:
        return {n for n, _ in self.added}

    def matches(self, globs: list[str], languages: list[str], exclude: list[str] | None = None) -> bool:
        if exclude and any(fnmatch(self.path, g) for g in exclude):
            return False
        lang_ok = "*" in languages or self.language in languages
        glob_ok = any(fnmatch(self.path, g) or fnmatch(PurePosixPath(self.path).name, g) for g in globs)
        return lang_ok and glob_ok


def parse(diff: str) -> list[FileDiff]:
    """Parse git-style or plain ``diff -u`` output. Deleted and binary files are dropped."""
    lines = diff.splitlines(keepends=True)
    files: list[FileDiff] = []
    cur: FileDiff | None = None
    buf: list[str] = []
    new_line = 0

    def flush() -> None:
        if cur is not None:
            cur.text = "".join(buf)
            if cur.path and not cur.deleted and not cur.binary:
                files.append(cur)

    i = 0
    while i < len(lines):
        line = lines[i]
        bare = line.rstrip("\r\n")
        nxt = lines[i + 1].rstrip("\r\n") if i + 1 < len(lines) else ""
        if bare.startswith("diff --git "):
            flush()
            m = re.match(r"diff --git a/(.+?) b/(.+)$", bare)
            cur, buf = FileDiff(path=m.group(2) if m else ""), []
        elif bare.startswith("--- ") and nxt.startswith("+++ "):
            # A header pair: new file unless we are still in this file's git preamble.
            if cur is None or _has_hunk(buf):
                flush()
                cur, buf = FileDiff(path=""), []
            target = nxt[4:].split("\t")[0].strip()
            if target == "/dev/null":
                cur.deleted = True
            else:
                cur.path = target[2:] if target.startswith("b/") else target
            buf.extend([line, lines[i + 1]])
            i += 2
            continue
        elif cur is not None and bare.startswith("Binary files"):
            cur.binary = True
        elif cur is not None:
            m = _HUNK.match(bare)
            if m:
                new_line = int(m.group(1))
            elif bare.startswith("+"):
                cur.added.append((new_line, bare[1:]))
                new_line += 1
            elif bare.startswith(" ") or bare == "":
                new_line += 1
        if cur is not None:
            buf.append(line)
        i += 1
    flush()
    return files


def _has_hunk(buf: list[str]) -> bool:
    return any(b.startswith("@@") for b in buf)


def render(files: list[FileDiff]) -> str:
    return "".join(f.text for f in files)


def chunk(files: list[FileDiff], max_chars: int) -> tuple[list[list[FileDiff]], list[str]]:
    """Group whole files into chunks of at most max_chars. Oversized files are skipped (reported)."""
    chunks: list[list[FileDiff]] = []
    skipped: list[str] = []
    cur: list[FileDiff] = []
    size = 0
    for f in files:
        n = len(f.text)
        if n > max_chars:
            skipped.append(f.path)
            continue
        if cur and size + n > max_chars:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(f)
        size += n
    if cur:
        chunks.append(cur)
    return chunks, skipped
