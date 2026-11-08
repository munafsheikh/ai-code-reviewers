"""Benchmark suite: protected fixtures with expected findings -> precision/recall/latency/stability."""

from __future__ import annotations

import itertools
import json
import statistics
import time
from pathlib import Path
from typing import Any

from orchestrator import config as cfg
from orchestrator.engine.review import run_review
from orchestrator.recovery.audit import Audit


def load_cases(root: Path) -> list[dict[str, Any]]:
    cases = []
    for d in sorted((root / "benchmarks" / "fixtures").iterdir()):
        if not d.is_dir():
            continue
        meta = cfg.load_toml(d / "case.toml")
        cases.append(
            {
                "id": d.name,
                "dir": d,
                "diff": (d / "diff.patch").read_text(encoding="utf-8"),
                "expected": json.loads((d / "expected.json").read_text())["findings"],
                **meta,
            }
        )
    return cases


def _matches(f: dict, e: dict) -> bool:
    if f["location"]["path"] != e["path"] or abs(f["location"]["start_line"] - e["line"]) > 1:
        return False
    if "rule_id" in e:
        return f["rule_id"] == e["rule_id"]
    return f["category"] == e.get("category")


def score(findings: list[dict], expected: list[dict], min_severity: str = "info") -> dict[str, int]:
    from orchestrator.contracts import severity_rank

    got = [f for f in findings if severity_rank(f["severity"]) >= severity_rank(min_severity)]
    tp_expected = set()
    fp = 0
    for f in got:
        hit = next((i for i, e in enumerate(expected) if i not in tp_expected and _matches(f, e)), None)
        if hit is None:
            fp += 1
        else:
            tp_expected.add(hit)
    tp = len(tp_expected)
    return {"tp": tp, "fp": fp, "fn": len(expected) - tp}


def _ratio(a: int, b: int) -> float:
    return round(a / b, 4) if b else 1.0


def run(profile: str = "offline", repeat: int = 1, root: Path | None = None) -> dict[str, Any]:
    root = root or cfg.home()
    rows = []
    totals = {"tp": 0, "fp": 0, "fn": 0}
    latencies = []
    stabilities = []
    for case in load_cases(root):
        runs = []
        for _ in range(max(1, repeat)):
            t0 = time.monotonic()
            res = run_review(case["diff"], profile, audit=Audit(log_stream=open("/dev/null", "w")), root=root)
            latencies.append((time.monotonic() - t0) * 1000)
            runs.append(res)
        s = score(runs[0]["findings"], case["expected"])
        for k in totals:
            totals[k] += s[k]
        fps = [{f["fingerprint"] for f in r["findings"]} for r in runs]
        jac = [len(a & b) / len(a | b) if a | b else 1.0 for a, b in itertools.combinations(fps, 2)] or [1.0]
        stabilities.append(min(jac))
        rows.append(
            {
                "case": case["id"],
                **s,
                "gate": runs[0]["gate"]["status"],
                "expected_gate": case.get("expected_gate"),
                "stability": round(min(jac), 4),
                "degraded": runs[0]["run"]["degraded"],
            }
        )
    tp, fp, fn = totals["tp"], totals["fp"], totals["fn"]
    precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    return {
        "schema": "acr.bench/v1",
        "profile": profile,
        "repeat": repeat,
        "cases": rows,
        "metrics": {
            "precision": precision,
            "recall": recall,
            "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
            "false_positive_rate": _ratio(fp, tp + fp) if tp + fp else 0.0,
            "gate_accuracy": _ratio(sum(1 for r in rows if r["expected_gate"] in (None, r["gate"])), len(rows)),
            "latency_ms_p50": round(statistics.median(latencies), 1) if latencies else 0.0,
            "latency_ms_max": round(max(latencies), 1) if latencies else 0.0,
            "stability_min": round(min(stabilities), 4) if stabilities else 1.0,
            **totals,
        },
    }


def check_thresholds(result: dict[str, Any], thresholds: dict[str, Any]) -> list[str]:
    m = result["metrics"]
    fails = []
    for key, bound in thresholds.items():
        if key.startswith("min_") and m[key[4:]] < bound:
            fails.append(f"{key[4:]} {m[key[4:]]} < {bound}")
        elif key.startswith("max_") and m[key[4:]] > bound:
            fails.append(f"{key[4:]} {m[key[4:]]} > {bound}")
    return fails


def to_markdown(result: dict[str, Any]) -> str:
    m = result["metrics"]
    out = [f"# Benchmark report — profile `{result['profile']}`", "", "| Metric | Value |", "|---|---|"]
    out += [f"| {k} | {v} |" for k, v in m.items()]
    out += ["", "| Case | TP | FP | FN | Gate | Expected gate | Stability |", "|---|---|---|---|---|---|---|"]
    out += [
        f"| {r['case']} | {r['tp']} | {r['fp']} | {r['fn']} | {r['gate']} | {r['expected_gate'] or '-'} | {r['stability']} |"
        for r in result["cases"]
    ]
    return "\n".join(out) + "\n"
