"""Turn model output into validated findings."""

from __future__ import annotations

import json
import re
from typing import Any

from orchestrator.config import Skill
from orchestrator.contracts import CONFIDENCES, Finding, Location
from orchestrator.engine.diff import FileDiff
from orchestrator.engine.rules import redact

_SEV_ALIASES = {
    "info": "info",
    "note": "info",
    "nit": "info",
    "style": "minor",
    "low": "minor",
    "minor": "minor",
    "warning": "minor",
    "medium": "major",
    "moderate": "major",
    "major": "major",
    "high": "major",
    "error": "major",
    "block": "critical",
    "blocker": "critical",
    "critical": "critical",
    "severe": "critical",
}


def extract_json(text: str) -> Any:
    """Find the first JSON object/array in text (tolerates code fences and prose)."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(text)
    dec = json.JSONDecoder()
    for cand in candidates:
        for i, ch in enumerate(cand):
            if ch in "{[":
                try:
                    obj, _ = dec.raw_decode(cand[i:])
                    return obj
                except json.JSONDecodeError:
                    continue
    raise ValueError("no JSON object found in model output")


def to_findings(text: str, skills: list[Skill], files: list[FileDiff], model: str) -> tuple[list[Finding], dict]:
    """Validate model findings against the diff. Returns findings and parse statistics."""
    stats = {"raw": 0, "accepted": 0, "discarded": 0, "unverified_location": 0, "parse_error": None}
    try:
        data = extract_json(text)
    except ValueError as e:
        stats["parse_error"] = str(e)
        return [], stats
    items = data.get("findings", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    by_path = {f.path: f for f in files}
    skill_ids = {s.id: s for s in skills}
    out: list[Finding] = []
    for item in items:
        stats["raw"] += 1
        f = _one(item, by_path, skill_ids, skills, model, stats)
        if f:
            out.append(f)
            stats["accepted"] += 1
        else:
            stats["discarded"] += 1
    return out, stats


def _one(
    item: Any, by_path: dict[str, FileDiff], skill_ids: dict[str, Skill], skills: list[Skill], model: str, stats: dict
) -> Finding | None:
    if not isinstance(item, dict):
        return None
    path = str(item.get("path") or item.get("file") or "").removeprefix("b/").strip()
    fd = by_path.get(path)
    if fd is None:  # a file not in the diff is a hallucination
        return None
    sev = _SEV_ALIASES.get(str(item.get("severity", "")).strip().lower())
    title = str(item.get("title") or item.get("issue") or "").strip()
    if not sev or not title:
        return None
    try:
        line = int(item.get("line") or 0)
    except (TypeError, ValueError):
        line = 0
    verified_loc = line in fd.changed_lines
    if not verified_loc:
        stats["unverified_location"] += 1
        line = line if line > 0 else (min(fd.changed_lines) if fd.changed_lines else 1)
    conf = str(item.get("confidence", "medium")).lower()
    conf = conf if conf in CONFIDENCES else "medium"
    if not verified_loc:
        conf = "low"
    skill = skill_ids.get(str(item.get("skill", ""))) or _infer_skill(
        title + " " + str(item.get("explanation", "")),
        [s for s in skills if fd.matches(s.file_globs, s.languages, s.exclude_globs)] or skills,
    )
    return Finding(
        rule_id=f"model.{skill.id}",
        skill=skill.id,
        title=title[:160],
        severity=sev,
        category=skill.category,
        location=Location(path, line, line, verified=verified_loc),
        explanation=str(item.get("explanation", title))[:1000],
        evidence=redact(str(item.get("evidence", ""))),
        remediation=str(item.get("remediation", ""))[:1000] or "Review and address manually.",
        confidence=conf,
        kind="hypothesis",
        source="model",
        model=model,
    )


_CATEGORY_HINTS = {
    "security": (
        "sql",
        "inject",
        "secret",
        "password",
        "credential",
        "token",
        "xss",
        "tls",
        "certificate",
        "deserial",
        "traversal",
        "ssrf",
        "eval",
        "command",
        "crypto",
    ),
    "performance": ("n+1", "performance", "quadratic", "blocking", "slow", "unbounded"),
    "testing": ("test",),
    "architecture": ("layer", "coupling", "design", "architecture"),
}


def _infer_skill(text: str, skills: list[Skill]) -> Skill:
    """Attribute an untagged model finding to the best-matching skill in the route."""
    low = text.lower()
    for category, hints in _CATEGORY_HINTS.items():
        if any(h in low for h in hints):
            match = next((s for s in skills if s.category == category), None)
            if match:
                return match
    return next((s for s in skills if s.category == "code-quality"), skills[0])


def legacy_severity(text: str) -> str:
    """Exact port of ReviewGate.extractSeverity: first SEVERITY line wins, fail open."""
    for line in text.split("\n"):
        t = line.strip()
        if t.upper().startswith("SEVERITY:"):
            val = t[t.index(":") + 1 :].strip().upper()
            if "BLOCK" in val:
                return "BLOCK"
            if "MINOR" in val:
                return "MINOR"
            return "NONE"
    return "NONE"
