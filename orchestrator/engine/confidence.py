"""Minimum confidence: which findings a review reports and lets through to the gate.

Every finding carries a confidence: ``low`` < ``medium`` < ``high``.
  rules     declare theirs in skill.toml (``high`` findings are reported as *verified*)
  models    say so per finding; ``medium`` when they do not, forced to ``low`` when the cited
            line is not one the diff changed

Findings below the minimum are left out of the result and cannot block; the result records
the minimum in force, where it came from, and how many findings (by severity) it hid, so a
raised threshold is never silent. The minimum is resolved, first match wins, from:
  1. ``--min-confidence`` on ``acr review`` / ``acr merge`` (the GitHub action's ``min-confidence``)
  2. ``$ACR_MIN_CONFIDENCE``
  3. the policy's ``[gate] min_confidence``
  4. the built-in default, ``low`` (report everything)
"""

from __future__ import annotations

import os
from typing import Any

from orchestrator.contracts import CONFIDENCES, SEVERITIES, confidence_rank

DEFAULT = "low"


class ConfidenceError(ValueError):
    pass


def _check(level: str, where: str) -> str:
    v = level.strip().lower()
    if v not in CONFIDENCES:
        raise ConfidenceError(f"{where}: confidence must be one of {', '.join(CONFIDENCES)}, got {level!r}")
    return v


def resolve(policy: dict, override: str | None = None, env: dict[str, str] | None = None) -> tuple[str, str]:
    """(minimum, source) by precedence: override > $ACR_MIN_CONFIDENCE > policy > default."""
    env = os.environ if env is None else env
    if override:
        return _check(override, "--min-confidence"), "--min-confidence"
    if env.get("ACR_MIN_CONFIDENCE", "").strip():
        return _check(env["ACR_MIN_CONFIDENCE"], "ACR_MIN_CONFIDENCE"), "ACR_MIN_CONFIDENCE"
    pol = policy.get("gate", {}).get("min_confidence")
    if pol:
        return _check(str(pol), f"policy {policy.get('id', '?')}"), f"policy {policy.get('id', '?')}"
    return DEFAULT, "default"


def split(findings: list[Any], minimum: str, conf=lambda f: f.confidence) -> tuple[list[Any], list[Any]]:
    """(kept, hidden) for findings (objects or dicts; ``conf`` reads the confidence)."""
    floor = confidence_rank(minimum)
    kept = [f for f in findings if confidence_rank(conf(f)) >= floor]
    hidden = [f for f in findings if confidence_rank(conf(f)) < floor]
    return kept, hidden


def record(minimum: str, source: str, hidden_severities: list[str], previously_hidden: dict[str, int] | None = None) -> dict:
    by_sev = {s: 0 for s in reversed(SEVERITIES)}
    for s, n in (previously_hidden or {}).items():
        by_sev[s] = by_sev.get(s, 0) + n
    for s in hidden_severities:
        by_sev[s] += 1
    return {"min": minimum, "source": source, "hidden": sum(by_sev.values()), "hidden_by_severity": by_sev}
