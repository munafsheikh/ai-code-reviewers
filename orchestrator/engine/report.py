"""Render a review result as JSON, SARIF 2.1.0, Markdown or the legacy text format."""

from __future__ import annotations

import json
from typing import Any

SARIF_LEVEL = {"critical": "error", "major": "error", "minor": "warning", "info": "note"}
SECURITY_SEVERITY = {"critical": "9.0", "major": "7.0", "minor": "4.0", "info": "1.0"}


def to_json(result: dict[str, Any]) -> str:
    return json.dumps(result, indent=2, sort_keys=False) + "\n"


def to_sarif(result: dict[str, Any]) -> str:
    rules: dict[str, dict] = {}
    results = []
    for f in result["findings"]:
        rules.setdefault(
            f["rule_id"],
            {
                "id": f["rule_id"],
                "name": f["rule_id"].replace(".", "_"),
                "shortDescription": {"text": f["title"]},
                "fullDescription": {"text": f["explanation"]},
                "help": {"text": f["remediation"]},
                **({"helpUri": f["links"]["rule"]} if (f.get("links") or {}).get("rule") else {}),
                "properties": {"tags": [f["category"], f["source"]], "security-severity": SECURITY_SEVERITY[f["severity"]]},
            },
        )
        r = {
            "ruleId": f["rule_id"],
            "level": SARIF_LEVEL[f["severity"]],
            "message": {"text": f"{f['title']}: {f['explanation']} Fix: {f['remediation']}"},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": f["location"]["path"]},
                        "region": {"startLine": max(1, f["location"]["start_line"])},
                    }
                }
            ],
            "partialFingerprints": {"acrFingerprint/v1": f["fingerprint"]},
            "properties": {
                "severity": f["severity"],
                "confidence": f["confidence"],
                "kind": f["kind"],
                "source": f["source"],
                "model": f["model"],
                "skill": f["skill"],
            },
        }
        if f.get("suppressed"):
            r["suppressions"] = [{"kind": "external", "justification": f["suppressed"]["reason"]}]
        results.append(r)
    run = result["run"]
    sarif = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": result["tool"]["name"],
                        "version": result["tool"]["version"],
                        "informationUri": "https://github.com/munafsheikh/ai-code-reviewers",
                        "rules": list(rules.values()),
                    }
                },
                "results": results,
                "invocations": [
                    {
                        "executionSuccessful": result["gate"]["status"] != "error",
                        "properties": {"profile": run["profile"], "degraded": run["degraded"], "gate": result["gate"]["status"]},
                    }
                ],
                "versionControlProvenance": (
                    [{"repositoryUri": run.get("repository") or "unknown", "revisionId": run["revision"]}] if run.get("revision") else []
                ),
            }
        ],
    }
    return json.dumps(sarif, indent=2) + "\n"


def to_markdown(result: dict[str, Any]) -> str:
    g, run, s = result["gate"], result["run"], result["summary"]
    icon = {"pass": "PASS", "warn": "WARN", "block": "BLOCK", "error": "ERROR"}[g["status"]]
    lines = [f"## AI code review: **{icon}**", ""]
    lines.append(
        f"Profile `{run['profile']}` · policy `{run['policy']['id']}@{run['policy']['version']}` · "
        f"{run['source']['files_reviewed']} files, {run['source']['added_lines']} added lines · "
        f"{run['duration_ms']} ms"
    )
    rl = run.get("links") or {}
    trace = []
    if rl.get("commit") and run.get("revision"):
        trace.append(f"commit [`{run['revision'][:7]}`]({rl['commit']})")
    if rl.get("ci_run"):
        trace.append(f"[CI run]({rl['ci_run']}) (JSON/SARIF report artifacts)")
    if rl.get("rules"):
        trace.append(f"[rule reference]({rl['rules']})")
    trace.append(f"`ai-code-reviewers {result['tool']['version']}` · run `{run['id'][:8]}`")
    lines.append("Reviewed " + " · ".join(trace))
    if run["degraded"]:
        lines += [
            "",
            "> **Degraded run:** " + "; ".join(run["infrastructure_errors"] or ["see recovery events"]) + ". Rule-based checks still ran.",
        ]
    models = ", ".join(f"`{m['ref']}`" for m in run["models"]) or "none (rules only)"
    lines += ["", f"Models: {models}"]
    lines += ["", "| Severity | Count |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in s["by_severity"].items()]
    if not result["findings"]:
        lines += ["", "No findings."]
    else:
        lines += ["", "| | Location | Finding | Basis |", "|---|---|---|---|"]
        for f in result["findings"]:
            loc = f"`{f['location']['path']}:{f['location']['start_line']}`"
            if (f.get("links") or {}).get("location"):
                loc = f"[{loc}]({f['links']['location']})"
            basis = f"{f['kind']}, {f['source']}" + (f" ({f['model']})" if f["model"] else "") + f", {f['confidence']}"
            sup = " *(baselined)*" if f.get("suppressed") else ""
            title = f["title"].replace("|", "\\|")
            lines.append(f"| {f['severity']} | {loc} | **{title}**{sup} | {basis} |")
        lines += ["", "<details><summary>Details and remediation</summary>", ""]
        for f in result["findings"]:
            fl = f.get("links") or {}
            rule = f"[`{f['rule_id']}`]({fl['rule']})" if fl.get("rule") else f"`{f['rule_id']}`"
            where = f"{f['location']['path']}:{f['location']['start_line']}"
            if fl.get("location"):
                where = f"[{where}]({fl['location']})"
            lines += [
                f"#### {rule} — {where}",
                f"{f['explanation']}",
                "",
                f"Evidence: `{f['evidence'].replace('`', '')}`",
                "",
                f"Fix: {f['remediation']}",
                "",
            ]
        lines.append("</details>")
    if g["reasons"]:
        lines += ["", "Gate reasons:", *[f"- {r}" for r in g["reasons"]]]
    lines += ["", "<sub>Model findings are hypotheses; rule findings marked *verified* are deterministic matches.</sub>"]
    return "\n".join(lines) + "\n"


def to_legacy(result: dict[str, Any]) -> str:
    """The SEVERITY/SUMMARY/ISSUES format parsed by the original Firefly gate."""
    if result["run"].get("legacy_raw_output") is not None:
        return result["run"]["legacy_raw_output"].strip() + "\n"
    g = result["gate"]
    active = [f for f in result["findings"] if not f.get("suppressed")]
    summary = f"{len(active)} finding(s)" if active else "no issues found"
    out = [f"SEVERITY: {g['legacy_severity']}", f"SUMMARY: {summary}"]
    if active:
        out.append("ISSUES:")
        out += [f"- {f['location']['path']}:{f['location']['start_line']} [{f['severity']}] {f['title']}" for f in active]
    return "\n".join(out) + "\n"


RENDERERS = {"json": to_json, "sarif": to_sarif, "markdown": to_markdown, "legacy": to_legacy}
EXTENSIONS = {"json": "review.json", "sarif": "review.sarif", "markdown": "review.md", "legacy": "review.txt"}
