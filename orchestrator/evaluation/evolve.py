"""Evidence-based improvement proposals (Phase 6, minimal).

Reads only local repository state and benchmark results; it never downloads,
installs or executes third-party skills or models. Output is a proposal for a
human-reviewed pull request, not an automatic change.
"""

from __future__ import annotations

import datetime as dt
import json
import re

from orchestrator import config as cfg
from orchestrator.evaluation import bench


def report() -> str:
    root = cfg.home()
    items: list[tuple[str, str, str]] = []  # (priority, area, text)
    skills = cfg.load_skills(root)
    expected_rules = {e["rule_id"] for c in bench.load_cases(root) for e in c["expected"] if "rule_id" in e}
    for s in skills.values():
        for r in s.rules:
            if r["id"] not in expected_rules:
                items.append(("P2", "benchmarks", f"Rule `{r['id']}` ({s.id}) has no benchmark fixture; add a positive case."))
    for m in cfg.load_models(root).values():
        if not m.digest:
            items.append(("P1", "models", f"`{m.id}` digest unpinned; run `acr models verify --pin` on a trusted runtime."))
        if m.status == "candidate":
            items.append(("P2", "models", f"`{m.id}` is a candidate; promote after a `bench --profile balanced` run."))
    res = bench.run("offline")
    gates = cfg.load_toml(root / "policies" / "quality-gates" / "benchmarks.toml")["offline"]
    for f in bench.check_thresholds(res, gates):
        items.append(("P0", "quality", f"Offline benchmark below threshold: {f}."))
    for path in [root / "compose.yaml", *sorted((root / "infrastructure" / "docker").glob("*Dockerfile*"))]:
        if path.exists():
            for line in path.read_text().splitlines():
                m = re.search(r"(?:image:|FROM)\s+(\S+)", line)
                ref = m.group(1) if m else ""
                if ref and "@sha256:" not in ref and not ref.startswith(("${", "acr-", "base")) and ref != "scratch":
                    items.append(("P1", "supply-chain", f"`{path.name}`: `{ref}` is not pinned by digest."))
    bl = json.loads((root / "policies" / "security" / "baseline.json").read_text())
    for e in bl.get("exceptions", []):
        days = (dt.date.fromisoformat(e["expires"]) - dt.date.today()).days
        if days < 14:
            items.append(("P1", "security", f"Baseline exception `{e['fingerprint']}` expires in {days} days."))
    items.sort()
    lines = [
        f"# Improvement proposal — {dt.date.today().isoformat()}",
        "",
        f"Offline benchmark: precision {res['metrics']['precision']}, recall {res['metrics']['recall']}, "
        f"gate accuracy {res['metrics']['gate_accuracy']}.",
        "",
        "| Priority | Area | Proposal |",
        "|---|---|---|",
    ]
    lines += [f"| {p} | {a} | {t} |" for p, a, t in items] or ["| - | - | No proposals. |"]
    lines += ["", "Each change must pass `make ci` and the benchmark quality gate before merge."]
    return "\n".join(lines) + "\n"
