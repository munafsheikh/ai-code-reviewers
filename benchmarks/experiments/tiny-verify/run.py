"""Candidate -> verify experiment: can tiny models adjudicate hyperspecific checks?

Each case is one candidate place that a cheap regex already found. Strategies answer the same
yes/no question ("is this a real instance of the check?") and are scored against the label:

  candidate   flag every candidate (the regex alone; recall is 1.0 by construction)
  rule        the repository's existing deterministic rule for the check, where one exists
  tool        a deterministic verifier (Python AST, shellcheck) where the check is structural
  model:<m>   a local model answers the check's single question about the marked line
  hybrid:<m>  tool where one exists, otherwise the model

Usage:
  python3 benchmarks/experiments/tiny-verify/run.py --models qwen2.5-coder:0.5b,qwen2.5-coder:1.5b \
      [--host http://127.0.0.1:11434] [--out .scratch/tiny-verify] [--check py.]

Stdlib only. Inputs are validated before any model call: every marked line must match its
check's candidate regex, and every check needs positive and negative cases.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

# Existing repository rules that target the same question (line-scoped regex + unless).
PY, JAVA, SH = (
    "skills/language-specific/python/skill.toml",
    "skills/language-specific/java/core/skill.toml",
    "skills/language-specific/shell/skill.toml",
)
REPO_RULES = {
    "py.random-secret": (PY, "PY-010"),
    "py.assert-guard": (PY, "PY-002"),
    "py.sql-format": ("skills/security/injection/skill.toml", "INJ-001,INJ-006"),  # INJ-006 defers to INJ-001
    "py.http-timeout": (PY, "PY-007"),
    "java.money-double": (JAVA, "JAVA-008"),
    "java.bigdecimal-equals": (JAVA, "JAVA-017"),
    "java.log-secret": (JAVA, "JAVA-018"),
    "bash.unquoted-var": (SH, "SH-001"),
    "bash.rm-empty-var": (SH, "SH-002"),
}

SYSTEM = (
    "You are a precise code reviewer. Answer only the question asked, about the line marked "
    'with ">>". Reply with JSON: {"answer": "yes"} or {"answer": "no"}.'
)
SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string", "enum": ["yes", "no"]}},
    "required": ["answer"],
}


def load() -> tuple[dict, list[dict]]:
    spec = tomllib.loads((HERE / "checks.toml").read_text())
    checks = {c["id"]: c | {"shots": []} for c in spec["check"]}
    for shot in spec.get("shot", []):
        checks[shot["check"]]["shots"].append(shot)
    cases = tomllib.loads((HERE / "cases.toml").read_text())["case"]
    errors = []
    for i, c in enumerate(cases):
        c["id"] = f"{c['check']}#{i}"
        c["code"] = c["code"].strip("\n")
        lines = c["code"].splitlines()
        if c["check"] not in checks:
            errors.append(f"{c['id']}: unknown check")
            continue
        if not 1 <= c["line"] <= len(lines):
            errors.append(f"{c['id']}: line {c['line']} out of range")
            continue
        if not re.search(checks[c["check"]]["candidate"], lines[c["line"] - 1]):
            errors.append(f"{c['id']}: marked line does not match the candidate regex")
    for cid in checks:
        labels = {c["label"] for c in cases if c["check"] == cid}
        if labels != {True, False}:
            errors.append(f"{cid}: needs both positive and negative cases")
    if errors:
        sys.exit("invalid inputs:\n  " + "\n  ".join(errors))
    return checks, cases


def marked(case: dict) -> str:
    return "\n".join((">> " if i == case["line"] else "   ") + line for i, line in enumerate(case["code"].splitlines(), 1))


# --- deterministic verifiers -------------------------------------------------------------
def _call_at(tree: ast.AST, line: int, names: set[str]) -> ast.Call | None:
    """The call on `line` whose method name is one of `names` (not a chained .json() etc.)."""
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and n.lineno == line and isinstance(n.func, ast.Attribute) and n.func.attr in names
    ]
    return min(calls, key=lambda n: n.col_offset) if calls else None


HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "request"}
SQL_METHODS = {"execute", "executemany"}


def _parse(code: str) -> ast.AST | None:
    try:
        return ast.parse(code)
    except SyntaxError:
        return None


def tool_py_timeout(case: dict) -> bool | None:
    tree = _parse(case["code"])
    call = tree and _call_at(tree, case["line"], HTTP_METHODS)
    if call is None:
        return None
    if any(k.arg is None for k in call.keywords):  # **kwargs may carry timeout: do not flag
        return False
    return not any(k.arg == "timeout" for k in call.keywords)


def _is_built_string(node: ast.AST, assigns: dict[str, ast.AST]) -> bool:
    if isinstance(node, ast.Name) and node.id in assigns:
        return _is_built_string(assigns[node.id], {})
    if isinstance(node, ast.JoinedStr):
        return any(isinstance(v, ast.FormattedValue) for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        return True
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format"


def tool_py_sql(case: dict) -> bool | None:
    tree = _parse(case["code"])
    call = tree and _call_at(tree, case["line"], SQL_METHODS)
    if call is None or not call.args:
        return None
    assigns = {t.id: n.value for n in ast.walk(tree) if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    return _is_built_string(call.args[0], assigns)


def tool_shellcheck(case: dict, code: str) -> bool | None:
    if not shutil.which("shellcheck"):
        return None
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=True) as fh:
        fh.write(case["code"] + "\n")
        fh.flush()
        out = subprocess.run(["shellcheck", "-f", "json", "-s", "bash", fh.name], capture_output=True, text=True, check=False).stdout
    issues = json.loads(out or "[]")
    want = int(code.removeprefix("SC"))
    return any(i["code"] == want and i["line"] == case["line"] for i in issues)


def run_tool(check: dict, case: dict) -> bool | None:
    tool = check.get("tool", "")
    if tool == "py-ast-timeout":
        return tool_py_timeout(case)
    if tool == "py-ast-sql":
        return tool_py_sql(case)
    if tool.startswith("shellcheck:"):
        return tool_shellcheck(case, tool.split(":", 1)[1])
    return None


def run_rule(check_id: str, case: dict) -> bool | None:
    if check_id not in REPO_RULES:
        return None
    path, rids = REPO_RULES[check_id]
    rules = tomllib.loads((ROOT / path).read_text())["rules"]
    return any(_fires(next(r for r in rules if r["id"] == rid), case) for rid in rids.split(","))


def _fires(rule: dict, case: dict) -> bool:
    lines = case["code"].splitlines()
    line = lines[case["line"] - 1]
    if rule.get("unless") and re.search(rule["unless"], line):
        return False
    if not re.search(rule["pattern"], line):
        return False
    if not rule.get("analyzer"):
        return True
    # The shipped rule's deterministic analyzer, exactly as the review engine runs it.
    sys.path.insert(0, str(ROOT))
    from orchestrator.engine import analyzers

    verdict = analyzers.get(rule["analyzer"])(lines, case["line"] - 1)
    return bool(verdict) or (verdict is None and rule.get("analyzer_fallback", "keep") == "keep")


# --- model verifier ----------------------------------------------------------------------
def _user(check: dict, code: str) -> str:
    return f"Question: {check['question']}\n\nCode ({check['lang']}):\n```\n{code}\n```"


def ask(host: str, model: str, check: dict, case: dict, shots: bool = False) -> tuple[bool | None, float, str]:
    messages = [{"role": "system", "content": SYSTEM}]
    for s in check["shots"] if shots else []:  # worked examples as prior turns
        messages += [
            {"role": "user", "content": _user(check, s["code"].strip("\n"))},
            {"role": "assistant", "content": json.dumps({"answer": s["answer"]})},
        ]
    messages.append({"role": "user", "content": _user(check, marked(case))})
    body = {
        "model": model,
        "messages": messages,
        "format": SCHEMA,
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "seed": 42, "num_predict": 16, "num_ctx": 4096},
    }
    req = urllib.request.Request(f"{host}/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=300) as r:
        text = json.load(r)["message"]["content"]
    dt = time.monotonic() - t0
    try:
        ans = json.loads(text)["answer"]
        return {"yes": True, "no": False}.get(ans), dt, text
    except (ValueError, KeyError, TypeError):
        return None, dt, text


# --- scoring -----------------------------------------------------------------------------
def score(rows: list[dict], strategy: str) -> dict:
    tp = fp = fn = tn = unanswered = 0
    for r in rows:
        pred = r["pred"].get(strategy)
        if pred is None:
            unanswered += 1
            pred = False  # no answer cannot block: counts as "not flagged"
        if pred and r["label"]:
            tp += 1
        elif pred:
            fp += 1
        elif r["label"]:
            fn += 1
        else:
            tn += 1
    p = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * rec / (p + rec) if p + rec else 0.0
    return {
        "n": len(rows),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "unanswered": unanswered,
        "precision": round(p, 3),
        "recall": round(rec, 3),
        "f1": round(f1, 3),
        "accuracy": round((tp + tn) / len(rows), 3) if rows else 0.0,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="qwen2.5-coder:0.5b")
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--out", default=str(ROOT / ".scratch" / "tiny-verify"))
    ap.add_argument("--check", default="", help="only checks whose id starts with this prefix")
    ap.add_argument("--shots", action="store_true", help="add the check's worked examples to the prompt")
    ap.add_argument("--kind", default="", help="only checks of this kind (semantic|structural)")
    a = ap.parse_args()
    checks, cases = load()
    cases = [c for c in cases if c["check"].startswith(a.check) and (not a.kind or checks[c["check"]]["kind"] == a.kind)]
    checks = {k: v for k, v in checks.items() if any(c["check"] == k for c in cases)}
    models = [m for m in a.models.split(",") if m]
    rows, latency = [], {m: [] for m in models}
    for c in cases:
        chk = checks[c["check"]]
        pred: dict[str, bool | None] = {"candidate": True, "rule": run_rule(c["check"], c), "tool": run_tool(chk, c)}
        raw = {}
        for m in models:
            ans, dt, text = ask(a.host, m, chk, c, a.shots)
            pred[f"model:{m}"] = ans
            pred[f"hybrid:{m}"] = pred["tool"] if pred["tool"] is not None else ans
            latency[m].append(dt)
            raw[m] = text
        rows.append({"id": c["id"], "check": c["check"], "kind": chk["kind"], "label": c["label"], "pred": pred, "raw": raw})
        print(f"{c['id']:<28} label={c['label']!s:<5} " + " ".join(f"{k}={v}" for k, v in pred.items()), flush=True)

    strategies = ["candidate", "rule", "tool"] + [f"{k}:{m}" for m in models for k in ("model", "hybrid")]
    result = {"models": models, "shots": a.shots, "cases": len(rows), "overall": {}, "by_kind": {}, "by_check": {}, "latency_s": {}}
    for s in strategies:
        covered = [r for r in rows if s not in ("rule", "tool") or r["pred"][s] is not None]
        result["overall"][s] = score(covered, s) | {"covered_checks": sorted({r["check"] for r in covered})}
        for kind in ("semantic", "structural"):
            result["by_kind"].setdefault(kind, {})[s] = score([r for r in covered if r["kind"] == kind], s)
        for cid in checks:
            sub = [r for r in covered if r["check"] == cid]
            if sub:
                result["by_check"].setdefault(cid, {})[s] = score(sub, s)
    for m, ts in latency.items():
        result["latency_s"][m] = {"mean": round(sum(ts) / len(ts), 2), "max": round(max(ts), 2)} if ts else {}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(result | {"rows": rows}, indent=2))
    (out / "results.md").write_text(markdown(result, strategies, checks))
    print((out / "results.md").read_text())


def markdown(res: dict, strategies: list[str], checks: dict) -> str:
    lines = ["| Strategy | Cases | Precision | Recall | F1 | Unanswered |", "|---|---|---|---|---|---|"]
    for s in strategies:
        o = res["overall"][s]
        lines.append(f"| `{s}` | {o['n']} | {o['precision']} | {o['recall']} | {o['f1']} | {o['unanswered']} |")
    lines += ["", "F1 by check:", "", "| Check | Kind | " + " | ".join(f"`{s}`" for s in strategies) + " |"]
    lines.append("|---|---|" + "---|" * len(strategies))
    for cid, per in res["by_check"].items():
        cells = [str(per[s]["f1"]) if s in per else "–" for s in strategies]
        lines.append(f"| {cid} | {checks[cid]['kind']} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "Mean / max latency per model call (s): " + ", ".join(f"`{m}` {v['mean']} / {v['max']}" for m, v in res["latency_s"].items() if v),
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
