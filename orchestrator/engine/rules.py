"""Deterministic, rule-based checks declared in skill manifests.

Rules match only added lines, so pre-existing code is not re-reported. A rule
finding is ``verified`` only when the rule declares high confidence; other
rule hits are recorded as hypotheses.
"""

from __future__ import annotations

import re
from fnmatch import fnmatch
from functools import lru_cache
from pathlib import PurePosixPath

from orchestrator.config import Skill
from orchestrator.contracts import Finding, Location
from orchestrator.engine.diff import FileDiff

_REDACT = re.compile(r"(?i)((?:password|passwd|secret|token|api[_-]?key)\s*[:=]\s*[\"']?)([^\"'\s]{4})[^\"'\s]*")


@lru_cache(maxsize=1024)
def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


def redact(text: str) -> str:
    """Keep evidence useful without republishing a secret in review output."""
    text = _REDACT.sub(lambda m: m.group(1) + m.group(2) + "****", text)
    text = re.sub(r"(AKIA[0-9A-Z]{4})[0-9A-Z]{12}", r"\1************", text)
    text = re.sub(r"(gh[pousr]_[A-Za-z0-9]{4})[A-Za-z0-9]{20,}", r"\1****", text)
    return text.strip()[:240]


def rule_applies(rule: dict, f: FileDiff) -> bool:
    langs = rule.get("languages")
    return not langs or "*" in langs or f.language in langs


def run_rules(skill: Skill, files: list[FileDiff]) -> list[Finding]:
    out: list[Finding] = []
    for f in files:
        if not f.matches(skill.file_globs, skill.languages, skill.exclude_globs):
            continue
        for rule in skill.rules:
            if not rule_applies(rule, f):
                continue
            rx = _rx(rule["pattern"])
            neg = _rx(rule["unless"]) if rule.get("unless") else None
            units = _blocks(f.added) if rule.get("scope") == "block" else [(n, t, [n]) for n, t in f.added]
            for _, text, line_map in units:
                for m in rx.finditer(text):
                    snippet = text[m.start() : m.end()]
                    if neg and neg.search(snippet if rule.get("scope") == "block" else text):
                        continue
                    line_no = line_map[text.count("\n", 0, m.start())]
                    end_no = line_map[text.count("\n", 0, max(m.start(), m.end() - 1))]
                    evidence = snippet if rule.get("scope") == "block" else text
                    conf = rule.get("confidence", "medium")
                    out.append(
                        Finding(
                            rule_id=rule["id"],
                            skill=skill.id,
                            title=rule["title"],
                            severity=rule["severity"],
                            category=skill.category,
                            location=Location(f.path, line_no, end_no),
                            explanation=rule["explanation"],
                            evidence=redact(" ".join(evidence.split())),
                            remediation=rule["remediation"],
                            confidence=conf,
                            kind="verified" if conf == "high" else "hypothesis",
                            source="rule",
                        )
                    )
                    if rule.get("scope") != "block":
                        break  # one finding per line per rule
    return out


def _blocks(added: list[tuple[int, str]]) -> list[tuple[int, str, list[int]]]:
    """Group consecutive added lines into blocks: (first_line, text, line_number_map)."""
    blocks: list[tuple[int, str, list[int]]] = []
    run: list[tuple[int, str]] = []
    for n, t in added:
        if run and n != run[-1][0] + 1:
            blocks.append((run[0][0], "\n".join(x for _, x in run), [x for x, _ in run]))
            run = []
        run.append((n, t))
    if run:
        blocks.append((run[0][0], "\n".join(x for _, x in run), [x for x, _ in run]))
    return blocks


def glob_hit(path: str, globs: list[str]) -> bool:
    name = PurePosixPath(path).name
    return any(fnmatch(path, g) or fnmatch(name, g) for g in globs)


def companion_trigger(c: dict, f: FileDiff) -> tuple[int, str] | None:
    """First (line, text) of ``f`` that triggers companion ``c``, or None."""
    if not glob_hit(f.path, c["when"]):
        return None
    if not c.get("pattern"):
        return f.added[0] if f.added else (1, "")
    rx = _rx(c["pattern"])
    return next(((n, t) for n, t in f.added if rx.search(t)), None)


def run_companions(skill: Skill, files: list[FileDiff]) -> list[Finding]:
    """Diff-level checks: a change to one kind of file must travel with a change to another.

    A companion fires once per diff when some file matching ``when`` (and, if set, an added
    line matching ``pattern``) changed but no file matching ``requires`` did. Typical use:
    user-facing surfaces (build, CI, CLI options, env vars, schemas) changed without docs.
    """
    out: list[Finding] = []
    for c in skill.companions:
        if any(glob_hit(f.path, c["requires"]) for f in files):
            continue
        hits = [(f, t) for f in files if f.matches(skill.file_globs, ["*"], skill.exclude_globs) and (t := companion_trigger(c, f))]
        if not hits:
            continue
        f, (line_no, text) = hits[0]
        triggered = sorted({x.path for x, _ in hits})
        conf = c.get("confidence", "medium")
        out.append(
            Finding(
                rule_id=c["id"],
                skill=skill.id,
                title=c["title"],
                severity=c["severity"],
                category=skill.category,
                location=Location(f.path, line_no, line_no),
                explanation=c["explanation"],
                evidence=redact(
                    f"changed {', '.join(triggered)}; nothing matching {' '.join(c['requires'])}"
                    + (f": {text}" if c.get("pattern") else "")
                ),
                remediation=c["remediation"],
                confidence=conf,
                kind="verified" if conf == "high" else "hypothesis",
                source="rule",
            )
        )
    return out
