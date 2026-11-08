"""Content-addressed, integrity-checked cache of model completions.

Deterministic generation settings + identical inputs => identical outputs, so
cached completions are safe to reuse and make repeated reviews cheap. Corrupt
entries are evicted and recomputed (an audited self-healing action).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from orchestrator.recovery.audit import Audit


def key_for(**parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


class CompletionCache:
    def __init__(self, directory: str | Path, audit: Audit, enabled: bool = True):
        self.dir = Path(directory)
        self.audit = audit
        self.enabled = enabled

    def _path(self, key: str) -> Path:
        return self.dir / key[:2] / f"{key}.json"

    def get(self, key: str) -> str | None:
        if not self.enabled:
            return None
        p = self._path(key)
        if not p.exists():
            return None
        try:
            entry = json.loads(p.read_text(encoding="utf-8"))
            text = entry["text"]
            if hashlib.sha256(text.encode()).hexdigest() != entry["sha256"] or entry["key"] != key:
                raise ValueError("checksum mismatch")
            return text
        except (ValueError, KeyError, OSError, json.JSONDecodeError) as e:
            self.audit.record("cache_entry_evicted", key=key[:12], reason=str(e))
            p.unlink(missing_ok=True)
            return None

    def put(self, key: str, text: str) -> None:
        if not self.enabled:
            return
        p = self._path(key)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            entry = {"key": key, "sha256": hashlib.sha256(text.encode()).hexdigest(), "text": text}
            fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(entry, fh)
            os.replace(tmp, p)  # atomic: readers never see partial entries
        except OSError as e:
            self.audit.record("cache_write_failed", key=key[:12], reason=str(e))
