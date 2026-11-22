"""Combine reviews of the same change that ran in parallel lanes (e.g. code, security, docs).

Each lane runs the full pipeline on a subset of skills. Merging re-assembles one result:
findings are de-duplicated by fingerprint, coverage is the union of what every lane checked
(so "every changed file was reviewed" is judged across lanes, not per lane), and the gate is
re-evaluated under one policy. The merged document validates against the same schema as a
single review, so every renderer and integration works on it unchanged.
"""

from __future__ import annotations

import copy
import dataclasses
import datetime as dt
import uuid
from typing import Any

from orchestrator.contracts import SEVERITIES, Finding, Location, severity_rank
from orchestrator.engine import coverage, gate


def _finding(d: dict) -> Finding:
    names = {f.name for f in dataclasses.fields(Finding)} - {"location"}
    loc_names = {f.name for f in dataclasses.fields(Location)}
    loc = Location(**{k: v for k, v in d["location"].items() if k in loc_names})
    return Finding(location=loc, **{k: v for k, v in d.items() if k in names})


def _union(items: list[dict], key: str) -> list[dict]:
    seen, out = set(), []
    for it in items:
        if it.get(key) not in seen:
            seen.add(it.get(key))
            out.append(it)
    return out


def _coverage(results: list[dict]) -> dict | None:
    covs = [r["run"].get("coverage") for r in results if r["run"].get("coverage")]
    if not covs:
        return None
    rows: dict[str, dict] = {}
    for c in covs:
        for row in c["files"]:
            cur = rows.setdefault(row["path"], {"path": row["path"], "kind": row["kind"], "categories": set()})
            cur["categories"] |= set(row["categories"])
    out = []
    for row in rows.values():
        cats = sorted(row["categories"])
        out.append(
            {"path": row["path"], "kind": row["kind"], "categories": cats, "covered": coverage.is_covered(row["path"], row["kind"], cats)}
        )
    return coverage.summarize(out)


def merge_results(results: list[dict], policy: dict, lane_names: list[str] | None = None) -> dict[str, Any]:
    if not results:
        raise ValueError("nothing to merge")
    names = lane_names or [f"lane{i + 1}" for i in range(len(results))]
    best: dict[str, dict] = {}
    for r in results:
        for f in r["findings"]:
            cur = best.get(f["fingerprint"])
            if cur is None or severity_rank(f["severity"]) > severity_rank(cur["severity"]):
                best[f["fingerprint"]] = f
    fdicts = sorted(best.values(), key=lambda f: (-severity_rank(f["severity"]), f["location"]["path"], f["location"]["start_line"]))
    runs = [r["run"] for r in results]
    run = copy.deepcopy(runs[0])
    infra = list(dict.fromkeys(e for x in runs for e in x["infrastructure_errors"]))
    cov = _coverage(results)
    run.update(
        id=str(uuid.uuid4()),
        started_at=min(x["started_at"] for x in runs),
        duration_ms=max(x["duration_ms"] for x in runs),  # lanes run in parallel
        profile=runs[0]["profile"] if len({x["profile"] for x in runs}) == 1 else "+".join(x["profile"] for x in runs),
        policy={"id": policy.get("id", "default"), "version": policy.get("version", "0")},
        source={
            "files_reviewed": max(x["source"]["files_reviewed"] for x in runs),
            "files_skipped": sorted({p for x in runs for p in x["source"]["files_skipped"]}),
            "added_lines": max(x["source"]["added_lines"] for x in runs),
        },
        skills=_union([s for x in runs for s in x["skills"]], "id"),
        models=_union([m for x in runs for m in x["models"]], "id"),
        routing=[r for x in runs for r in x["routing"]],
        calls={k: sum(x["calls"].get(k, 0) for x in runs) for k in runs[0]["calls"]},
        parse=[p for x in runs for p in x.get("parse") or []],
        degraded=any(x["degraded"] for x in runs),
        infrastructure_errors=infra,
        instructions=_union([i for x in runs for i in x.get("instructions") or []], "sha256"),
        coverage=cov,
        recovery_events=[e for x in runs for e in x["recovery_events"]],
        lanes=[
            {"name": n, "run_id": x["id"], "profile": x["profile"], "skills": [s["id"] for s in x["skills"]], "degraded": x["degraded"]}
            for n, x in zip(names, runs, strict=True)
        ],
    )
    g = gate.evaluate([_finding(f) for f in fdicts], policy, infra, cov["uncovered"] if cov else None)
    merged = copy.deepcopy(results[0])
    merged.update(
        run=run,
        findings=fdicts,
        summary={
            "total": len(fdicts),
            "by_severity": {s: sum(1 for f in fdicts if f["severity"] == s) for s in reversed(SEVERITIES)},
            "by_source": {s: sum(1 for f in fdicts if f["source"] == s) for s in ("rule", "model")},
            "verified": sum(1 for f in fdicts if f["kind"] == "verified"),
        },
        gate=g,
    )
    merged["run"]["merged_at"] = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    return merged
