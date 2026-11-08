"""`acr validate`: structural, schema, rule-example and permission checks for the repository."""

from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

from orchestrator import config as cfg
from orchestrator import schema

REQUIRED_FILES = [
    "README.md",
    "LICENSE",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "Makefile",
    ".env.example",
    "compose.yaml",
    "pyproject.toml",
]
NETWORK_MODULES = {"socket", "urllib", "urllib.request", "http.client", "requests", "httpx", "aiohttp", "orchestrator.engine.http"}
SUBPROCESS_MODULES = {"subprocess", "pty", "multiprocessing"}
SUBPROCESS_CALLS = {"system", "popen", "execv", "execve", "execvp", "spawnv", "spawnl", "startfile"}


class Report:
    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.checked = 0

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def check_structure(root: Path, r: Report) -> None:
    for f in REQUIRED_FILES:
        r.checked += 1
        if not (root / f).exists():
            r.err(f"missing required file: {f}")


def check_skills(root: Path, r: Report) -> None:
    seen_ids, seen_rules = {}, {}
    for mf in sorted((root / "skills").rglob("skill.toml")):
        rel = mf.relative_to(root)
        d = cfg.load_toml(mf)
        r.checked += 1
        for e in schema.validate(d, schema.load("skill")):
            r.err(f"{rel}: {e}")
        sid = d.get("id")
        if sid in seen_ids:
            r.err(f"{rel}: duplicate skill id {sid} (also {seen_ids[sid]})")
        seen_ids[sid] = rel
        p = d.get("prompt")
        if p and not (mf.parent / p.get("file", "")).exists():
            r.err(f"{rel}: prompt file {p.get('file')} not found")
        if d.get("tier", "none") != "none" and not p:
            r.err(f"{rel}: tier {d['tier']} requires a [prompt]")
        if not p and not d.get("rules"):
            r.err(f"{rel}: skill has neither rules nor a prompt")
        for rule in d.get("rules", []):
            rid = rule.get("id")
            if rid in seen_rules:
                r.err(f"{rel}: duplicate rule id {rid} (also {seen_rules[rid]})")
            seen_rules[rid] = rel
            try:
                rx = re.compile(rule["pattern"])
                neg = re.compile(rule["unless"]) if rule.get("unless") else None
            except (re.error, KeyError) as e:
                r.err(f"{rel}: rule {rid}: invalid regex: {e}")
                continue
            ex = rule.get("examples", {})
            for s in ex.get("match", []):
                r.checked += 1
                if not (rx.search(s) and not (neg and neg.search(s))):
                    r.err(f"{rel}: rule {rid} should match example {s!r}")
            for s in ex.get("no_match", []):
                r.checked += 1
                if rx.search(s) and not (neg and neg.search(s)):
                    r.err(f"{rel}: rule {rid} should NOT match example {s!r}")


def check_models(root: Path, r: Report) -> None:
    for mf in sorted((root / "models" / "registry").glob("*.toml")):
        rel = mf.relative_to(root)
        d = cfg.load_toml(mf)
        r.checked += 1
        for e in schema.validate(d, schema.load("model")):
            r.err(f"{rel}: {e}")
        if d.get("id") != mf.stem:
            r.err(f"{rel}: id {d.get('id')!r} must equal the file name")
        if d.get("status") == "approved" and not d.get("integrity", {}).get("digest"):
            r.err(f"{rel}: approved models must have a pinned digest")
        if not d.get("integrity", {}).get("digest"):
            r.warn(f"{rel}: digest not pinned (status {d.get('status')})")


def _imports(tree: ast.AST) -> set[str]:
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
            mods |= {f"{node.module}.{a.name}" for a in node.names}
    return mods


def check_wrapper_permissions(manifest: dict, source: str) -> list[str]:
    """Static least-privilege check: code may only use capabilities its manifest declares."""
    perms = manifest.get("permissions", {})
    tree = ast.parse(source)
    mods = _imports(tree)
    problems = []
    if not perms.get("subprocess"):
        bad = {m for m in mods if m.split(".")[0] in SUBPROCESS_MODULES}
        calls = {
            n.attr
            for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and n.attr in SUBPROCESS_CALLS and isinstance(n.value, ast.Name) and n.value.id == "os"
        }
        if bad or calls:
            problems.append(f"uses process execution ({', '.join(sorted(bad | calls))}) but permissions.subprocess = false")
    if perms.get("network") == "none":
        bad = {m for m in mods if m in NETWORK_MODULES or m.split(".")[0] in {"socket", "requests", "httpx", "aiohttp"}}
        if bad:
            problems.append(f"uses network modules ({', '.join(sorted(bad))}) but permissions.network = none")
    elif perms.get("network") == "allowlist":
        raw = {
            m
            for m in mods
            if m.split(".")[0] in {"socket", "requests", "httpx", "aiohttp"} or m.startswith("urllib") or m.startswith("http.client")
        }
        if raw:
            problems.append(f"bypasses the egress allowlist ({', '.join(sorted(raw))}); use orchestrator.engine.http")
    if perms.get("filesystem") == "none":
        opens = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "open"]
        if opens:
            problems.append("calls open() but permissions.filesystem = none")
    return problems


def check_wrappers(root: Path, r: Report) -> None:
    for mf in sorted((root / "wrappers").rglob("wrapper.toml")):
        rel = mf.relative_to(root)
        d = cfg.load_toml(mf)
        r.checked += 1
        for e in schema.validate(d, schema.load("wrapper")):
            r.err(f"{rel}: {e}")
        file = d.get("entrypoint", ":").split(":")[0]
        src = mf.parent / file
        if not src.exists():
            r.err(f"{rel}: entrypoint file {file} not found")
            continue
        for p in check_wrapper_permissions(d, src.read_text(encoding="utf-8")):
            r.err(f"{rel}: permission violation: {p}")


def check_profiles(root: Path, r: Report) -> None:
    skills = cfg.load_skills(root)
    models = cfg.load_models(root)
    wrappers = {cfg.load_toml(m)["id"] for m in (root / "wrappers").rglob("wrapper.toml")}
    for mf in sorted((root / "profiles").glob("*/profile.toml")):
        rel = mf.relative_to(root)
        r.checked += 1
        p = cfg.load_profile(mf.parent.name, root)
        for e in schema.validate(p, schema.load("profile")):
            r.err(f"{rel}: {e}")
        if not cfg.select_skills(p.get("skills", []), skills):
            r.err(f"{rel}: skill selection matches no skills")
        if p.get("runtime", {}).get("wrapper") not in wrappers:
            r.err(f"{rel}: unknown wrapper {p.get('runtime', {}).get('wrapper')}")
        if not (root / "policies" / "review" / f"{p.get('policy')}.toml").exists():
            r.err(f"{rel}: unknown policy {p.get('policy')}")
        for tier in p.get("routing", {}).get("tiers", []):
            name = p["routing"].get(f"{tier}_model", "")
            if name and name not in models:
                r.warn(f"{rel}: {tier}_model {name!r} is not in the model registry")


def check_policies(root: Path, r: Report) -> None:
    for mf in sorted((root / "policies" / "review").glob("*.toml")):
        r.checked += 1
        d = cfg.load_toml(mf)
        for key in ("id", "version", "gate"):
            if key not in d:
                r.err(f"{mf.relative_to(root)}: missing '{key}'")
    bl = root / "policies" / "security" / "baseline.json"
    if bl.exists():
        data = json.loads(bl.read_text())
        for i, e in enumerate(data.get("exceptions", [])):
            r.checked += 1
            missing = [k for k in ("fingerprint", "reason", "expires", "owner") if not e.get(k)]
            if missing:
                r.err(f"baseline exception #{i}: missing {missing}")
            elif dt.date.fromisoformat(e["expires"]) < dt.date.today():
                r.warn(f"baseline exception {e['fingerprint']} expired on {e['expires']}")


def fixture_manifest(root: Path) -> str:
    fx = root / "benchmarks" / "fixtures"
    lines = []
    for f in sorted(p for p in fx.rglob("*") if p.is_file() and p.name != "MANIFEST.sha256"):
        lines.append(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.relative_to(fx).as_posix()}")
    return "\n".join(lines) + "\n"


def check_fixtures(root: Path, r: Report) -> None:
    mf = root / "benchmarks" / "fixtures" / "MANIFEST.sha256"
    r.checked += 1
    if not mf.exists():
        r.err("benchmarks/fixtures/MANIFEST.sha256 missing (run: acr bench --update-manifest)")
    elif mf.read_text() != fixture_manifest(root):
        r.err("protected benchmark fixtures changed without updating MANIFEST.sha256 (acr bench --update-manifest)")


def run(root: Path | None = None, skip: set[str] | None = None) -> Report:
    root = root or cfg.home()
    r = Report()
    for check in (check_structure, check_skills, check_models, check_wrappers, check_profiles, check_policies, check_fixtures):
        if check.__name__.removeprefix("check_") in (skip or set()):
            continue
        try:
            check(root, r)
        except Exception as e:  # noqa: BLE001 - a crashing check is itself a validation failure
            r.err(f"{check.__name__} crashed: {type(e).__name__}: {e}")
    return r
