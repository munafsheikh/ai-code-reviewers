"""Attack-surface inventory: listening ports, network egress, privileges, wrappers' declared capabilities."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    compose = (ROOT / "compose.yaml").read_text()
    print("### Attack surface\n")
    print("| Item | Value |\n|---|---|")
    for port in re.findall(r'^\s*-\s*"([^"]+:\d+)"', compose, re.M):
        print(f"| Published port | `{port}` |")
    print(f"| Internal-only network | {'yes' if 'internal: true' in compose else 'NO'} |")
    caps = 'cap_drop: ["ALL"]' in compose
    print(f"| Containers drop all capabilities | {'yes' if caps else 'NO'} |")
    print(f"| Read-only root filesystems | {'yes' if 'read_only: true' in compose else 'NO'} |")
    df = (ROOT / "infrastructure/docker/Dockerfile").read_text()
    print(f"| Reviewer runs as non-root | {'yes' if 'USER 10001' in df else 'NO'} |")
    for mf in sorted((ROOT / "wrappers").rglob("wrapper.toml")):
        d = tomllib.loads(mf.read_text())
        p = d["permissions"]
        print(f"| Wrapper `{d['id']}` | network={p['network']}, subprocess={p['subprocess']}, filesystem={p['filesystem']} |")
    print("| HTTP endpoints | `/healthz`, `/readyz`, `/metrics`, `POST /v1/review` (size-limited, concurrency-limited) |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
