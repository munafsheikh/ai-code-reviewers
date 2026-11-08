"""Audit trail for recovery and degradation actions (embedded in every result)."""

from __future__ import annotations

import json
import sys
import time
from typing import Any


class Audit:
    def __init__(self, log_stream=None):
        self.events: list[dict[str, Any]] = []
        self._log = log_stream if log_stream is not None else sys.stderr

    def record(self, action: str, **detail: Any) -> None:
        ev = {"ts": round(time.time(), 3), "action": action, **detail}
        self.events.append(ev)
        # Structured log line on stderr; stdout is reserved for review output.
        print(json.dumps({"level": "info", "component": "recovery", **ev}), file=self._log)
