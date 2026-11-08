"""Markdown diff of two CycloneDX SBOMs (added / removed / changed components)."""

import json
import sys


def comps(path):
    data = json.load(open(path, encoding="utf-8"))
    return {(c.get("type"), c.get("name")): c.get("version") for c in data.get("components", [])}


def main(base, head):
    b, h = comps(base), comps(head)
    added = sorted(k for k in h if k not in b)
    removed = sorted(k for k in b if k not in h)
    changed = sorted(k for k in h if k in b and h[k] != b[k])
    print("### SBOM diff\n")
    print(f"{len(added)} added, {len(removed)} removed, {len(changed)} changed (of {len(h)} components)\n")
    for title, keys, fmt in (
        ("Added", added, lambda k: f"{k[1]} {h[k]}"),
        ("Removed", removed, lambda k: f"{k[1]} {b[k]}"),
        ("Changed", changed, lambda k: f"{k[1]} {b[k]} -> {h[k]}"),
    ):
        if keys:
            print(f"**{title}**\n")
            print("\n".join(f"- {fmt(k)} ({k[0]})" for k in keys) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:3]))
