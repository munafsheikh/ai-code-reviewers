"""Fail when a tracked security/review exception has expired (no silent long-lived suppressions)."""

import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    today = dt.date.today()
    expired = []
    for line in (ROOT / "policies/security/trivyignore").read_text().splitlines():
        m = re.match(r"^(\S+)\s+#.*expires (\d{4}-\d{2}-\d{2})", line)
        if m and dt.date.fromisoformat(m.group(2)) < today:
            expired.append(f"trivyignore {m.group(1)} expired {m.group(2)}")
    for e in json.loads((ROOT / "policies/security/baseline.json").read_text())["exceptions"]:
        if dt.date.fromisoformat(e["expires"]) < today:
            expired.append(f"baseline {e['fingerprint']} expired {e['expires']}")
    print("\n".join(expired) or "exceptions: none expired")
    return 1 if expired else 0


if __name__ == "__main__":
    sys.exit(main())
