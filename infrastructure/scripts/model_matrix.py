"""Plan and report the model-matrix evaluation (stdlib only; runs via py.sh or the toolbox).

model_matrix.py plan  --select <all|small|changed|ids...> [--max-disk-mb N] [--base REF]
    prints a JSON list of {id, ref, disk_mb} for the GitHub Actions matrix
model_matrix.py report <results-dir>
    prints a Markdown comparison of bench results + pull/digest evidence
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def manifests() -> dict[str, dict]:
    out = {}
    for f in sorted((ROOT / "models/registry").glob("*.toml")):
        d = tomllib.loads(f.read_text())
        out[d["id"]] = d
    return out


def plan(args: list[str]) -> int:
    select, max_disk, base = "small", 6000, "origin/main"
    ids: list[str] = []
    it = iter(args)
    for a in it:
        if a == "--select":
            select = next(it)
        elif a == "--max-disk-mb":
            max_disk = int(next(it))
        elif a == "--base":
            base = next(it)
        else:
            ids.append(a)
    ms = manifests()
    if select == "all":
        chosen = list(ms)
    elif select == "small":
        chosen = [i for i, d in ms.items() if d["tier"] == "small"]
    elif select == "changed":
        diff = subprocess.run(
            ["git", "-C", str(ROOT), "diff", "--name-only", f"{base}...HEAD", "--", "models/registry"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.split()
        chosen = [Path(p).stem for p in diff if Path(p).stem in ms]
    else:
        chosen = [i for i in select.split() + ids if i in ms]
    rows, skipped = [], []
    for i in chosen:
        d = ms[i]
        (rows if d["resources"]["disk_mb"] <= max_disk else skipped).append(
            {"id": i, "ref": d["source"]["ref"], "disk_mb": d["resources"]["disk_mb"]}
        )
    for s in skipped:
        print(f"skipped {s['id']}: {s['disk_mb']} MB exceeds runner budget {max_disk} MB (use a larger runner)", file=sys.stderr)
    print(json.dumps(rows))
    return 0


def report(results_dir: str) -> int:
    ms = manifests()
    rows = []
    for d in sorted(Path(results_dir).glob("*/result.json")):
        r = json.loads(d.read_text())
        rows.append(r)
    print("### Model matrix\n")
    print("| Model | Ref | Pulled | Digest | Precision | Recall | Gate acc. | Degraded runs | p50 ms | License class |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        b = r.get("bench") or {}
        m = b.get("metrics", {})
        degraded = sum(1 for c in b.get("cases", []) if c.get("degraded"))
        print(
            f"| `{r['id']}` | `{r['ref']}` | {'yes' if r['pulled'] else 'NO'} | `{(r.get('digest') or '-')[:12]}` | "
            f"{m.get('precision', '-')} | {m.get('recall', '-')} | {m.get('gate_accuracy', '-')} | "
            f"{degraded}/{len(b.get('cases', []))} | {m.get('latency_ms_p50', '-')} | {ms.get(r['id'], {}).get('license_class', '?')} |"
        )
    print(
        "\nPull success verifies the runtime tag exists; digests can be pinned with `acr models verify --pin`. "
        "Precision counts model findings against fixtures that list only rule-level expectations, "
        "so extra correct model findings lower it: compare models relative to each other."
    )
    return 0 if all(r["pulled"] for r in rows) else 1


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:] or ["plan"]
    raise SystemExit(plan(rest) if cmd == "plan" else report(rest[0]))
