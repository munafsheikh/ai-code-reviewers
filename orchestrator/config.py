"""Discovery and loading of profiles, policies, skills, models and wrappers.

All definitions are TOML files under ACR_HOME (default: the repository root
that contains this package). Values can be overridden by environment
variables so the same image runs locally, in CI and as a service.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any


def home() -> Path:
    env = os.environ.get("ACR_HOME")
    return Path(env).resolve() if env else Path(__file__).resolve().parent.parent


def load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


@dataclass
class Skill:
    id: str
    version: str
    category: str
    description: str
    path: Path
    languages: list[str]
    file_globs: list[str]
    exclude_globs: list[str]
    tier: str
    prompt: str | None
    output: str
    rules: list[dict[str, Any]]
    raw: dict[str, Any] = field(repr=False, default_factory=dict)
    companions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ModelManifest:
    id: str
    tier: str
    ref: str
    runtime: str
    license: str
    digest: str
    context_tokens: int
    min_ram_mb: int
    status: str
    license_class: str = "unknown"
    params_b: float = 0.0
    kind: str = "instruct"
    hf: str = ""
    raw: dict[str, Any] = field(repr=False, default_factory=dict)
    registered: bool = True

    def ref_for(self, wrapper: str) -> str:
        """Model name to send to a runtime: Ollama tag by default, HF repo id for OpenAI-compatible servers."""
        if wrapper == "llama-cpp" and self.hf:
            return self.hf
        return self.ref


def load_skills(root: Path | None = None) -> dict[str, Skill]:
    root = root or home()
    out: dict[str, Skill] = {}
    for mf in sorted((root / "skills").rglob("skill.toml")):
        d = load_toml(mf)
        prompt_cfg = d.get("prompt") or {}
        prompt = None
        if prompt_cfg.get("file"):
            prompt = (mf.parent / prompt_cfg["file"]).read_text(encoding="utf-8")
        out[d["id"]] = Skill(
            id=d["id"],
            version=d["version"],
            category=d["category"],
            description=d.get("description", ""),
            path=mf.parent,
            languages=d.get("languages", ["*"]),
            file_globs=d.get("file_globs", ["*"]),
            exclude_globs=d.get("exclude_globs", []),
            tier=d.get("tier", "none"),
            prompt=prompt,
            output=prompt_cfg.get("output", "findings-json"),
            rules=d.get("rules", []),
            raw=d,
            companions=d.get("companions", []),
        )
    return out


def load_models(root: Path | None = None) -> dict[str, ModelManifest]:
    root = root or home()
    out: dict[str, ModelManifest] = {}
    for mf in sorted((root / "models" / "registry").glob("*.toml")):
        d = load_toml(mf)
        out[d["id"]] = ModelManifest(
            id=d["id"],
            tier=d["tier"],
            ref=d["source"]["ref"],
            runtime=d["source"]["runtime"],
            license=d["license"],
            digest=d.get("integrity", {}).get("digest", ""),
            context_tokens=d["limits"]["context_tokens"],
            min_ram_mb=d["resources"]["min_ram_mb"],
            status=d["status"],
            license_class=d.get("license_class", "unknown"),
            params_b=float(d.get("params_b", 0)),
            kind=d.get("kind", "instruct"),
            hf=d["source"].get("hf", ""),
            raw=d,
        )
    return out


def resolve_model(name: str, models: dict[str, ModelManifest], tier: str = "small") -> ModelManifest:
    """Registry id -> manifest; anything else is treated as an unregistered runtime ref."""
    if name in models:
        return models[name]
    for m in models.values():
        if m.ref == name:
            return m
    return ModelManifest(
        id=name,
        tier=tier,
        ref=name,
        runtime="unknown",
        license="unknown",
        digest="",
        context_tokens=8192,
        min_ram_mb=0,
        status="unregistered",
        registered=False,
    )


def load_wrappers(root: Path | None = None) -> dict[str, dict[str, Any]]:
    root = root or home()
    out = {}
    for mf in sorted((root / "wrappers").glob("*/wrapper.toml")):
        d = load_toml(mf)
        d["_dir"] = mf.parent
        out[d["id"]] = d
    return out


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_profile(name: str, root: Path | None = None) -> dict[str, Any]:
    root = root or home()
    path = Path(name) if name.endswith(".toml") else root / "profiles" / name / "profile.toml"
    d = load_toml(path)
    if "extends" in d:
        d = _deep_merge(load_profile(d.pop("extends"), root), d)
    return d


def load_policy(name: str, root: Path | None = None) -> dict[str, Any]:
    root = root or home()
    path = Path(name) if name.endswith(".toml") else root / "policies" / "review" / f"{name}.toml"
    return load_toml(path)


def select_skills(patterns: list[str], skills: dict[str, Skill]) -> list[Skill]:
    return [s for sid, s in sorted(skills.items()) if any(fnmatch(sid, p) for p in patterns)]


def env_overrides(profile: dict[str, Any]) -> dict[str, Any]:
    """Apply ACR_* (and legacy LLM_*) environment overrides to a loaded profile."""
    p = _deep_merge(profile, {})
    runtime = p.setdefault("runtime", {})
    host = os.environ.get("ACR_MODEL_HOST") or os.environ.get("LLM_HOST")
    if host:
        runtime["base_url"] = host
    routing = p.setdefault("routing", {})
    # LLM_MODEL: legacy ReviewGate compatibility. An empty value only means "no model" in the
    # legacy profile (ReviewGate exits 2 without one); elsewhere it is ignored, so CI systems that
    # forward an unset variable as "" do not silently disable the profile's model.
    legacy = profile.get("mode") == "legacy"
    for var in ("ACR_SMALL_MODEL", "LLM_MODEL"):
        if var in os.environ and (os.environ[var].strip() or legacy):
            routing["small_model"] = os.environ[var]
            break
    if os.environ.get("ACR_LARGE_MODEL"):
        routing["large_model"] = os.environ["ACR_LARGE_MODEL"]
    if os.environ.get("ACR_MEMORY_BUDGET_MB"):
        p.setdefault("budget", {})["memory_budget_mb"] = int(os.environ["ACR_MEMORY_BUDGET_MB"])
    if os.environ.get("ACR_CACHE_DIR"):
        p.setdefault("cache", {})["dir"] = os.environ["ACR_CACHE_DIR"]
    if os.environ.get("ACR_WRAPPER"):
        runtime["wrapper"] = os.environ["ACR_WRAPPER"]
    return p
