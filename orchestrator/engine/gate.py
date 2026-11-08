"""Quality gate: policy + findings (+ baseline exceptions) -> pass / warn / block / error."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from orchestrator.contracts import Finding, confidence_rank, severity_rank
from orchestrator.engine.coverage import is_doc
from orchestrator.recovery.audit import Audit


def load_baseline(path: Path | None) -> list[dict]:
    if not path or not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("exceptions", [])


def apply_baseline(findings: list[Finding], exceptions: list[dict], audit: Audit, today: dt.date | None = None) -> None:
    today = today or dt.date.today()
    index = {e["fingerprint"]: e for e in exceptions}
    for f in findings:
        e = index.get(f.fingerprint)
        if not e:
            continue
        if dt.date.fromisoformat(e["expires"]) < today:
            audit.record("baseline_exception_expired", fingerprint=f.fingerprint, expires=e["expires"])
            continue
        # Suppressed findings stay in every report; only the gate ignores them.
        f.suppressed = {"reason": e["reason"], "expires": e["expires"], "owner": e.get("owner", "")}


def evaluate(findings: list[Finding], policy: dict, infra_errors: list[str], uncovered: list[str] | None = None) -> dict:
    g = policy.get("gate", {})
    block_on = severity_rank(g.get("block_on", "major"))
    warn_on = severity_rank(g.get("warn_on", "minor"))
    model_can_block = g.get("model_findings_can_block", True)
    model_min_conf = confidence_rank(g.get("model_min_confidence_to_block", "low"))
    reasons: list[str] = []
    active = [f for f in findings if not f.suppressed]
    blocking = [
        f
        for f in active
        if severity_rank(f.severity) >= block_on
        and (f.source == "rule" or (model_can_block and confidence_rank(f.confidence) >= model_min_conf))
    ]
    warning = [f for f in active if severity_rank(f.severity) >= warn_on]
    # Files no active code / documentation check examined: blocking only when the policy requires coverage.
    gaps = list(uncovered or []) if g.get("require_coverage", False) else []
    if infra_errors and g.get("fail_on_infrastructure_error", False):
        status, code = "error", 2
        reasons.append("model infrastructure unavailable and policy requires it")
    elif blocking or gaps:
        status, code = "block", 1
        reasons += [f"{f.severity} {f.rule_id} at {f.location.path}:{f.location.start_line}" for f in blocking[:20]]
        reasons += [f"no {'documentation' if is_doc(p) else 'code'} review coverage for {p}" for p in gaps[:20]]
    elif warning:
        status, code = "warn", 0
    else:
        status, code = "pass", 0
    legacy = {"block": "BLOCK", "warn": "MINOR"}.get(status, "NONE")
    return {
        "status": status,
        "exit_code": code,
        "legacy_severity": legacy,
        "reasons": reasons,
        "blocking_findings": len(blocking),
        "suppressed_findings": len(findings) - len(active),
        "uncovered_files": len(gaps),
    }
