"""Review pipeline: diff -> rules + routed model calls -> merged findings -> gate -> result."""

from __future__ import annotations

import datetime as dt
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from orchestrator import __version__
from orchestrator import config as cfg
from orchestrator.contracts import RESULT_SCHEMA, SEVERITIES, AdapterError, Finding, GenerationRequest, ModelAdapter
from orchestrator.engine import diff as diffmod
from orchestrator.engine import gate, parse, prompt
from orchestrator.engine.adapters import load_adapter
from orchestrator.engine.rules import run_companions, run_rules
from orchestrator.recovery.audit import Audit
from orchestrator.recovery.cache import CompletionCache, key_for
from orchestrator.recovery.retry import CircuitBreaker, call_with_retry
from orchestrator.routing import router


class ReviewContext:
    def __init__(self, profile: dict, policy: dict, audit: Audit, root: Path):
        self.profile, self.policy, self.audit, self.root = profile, policy, audit, root
        b = profile.get("budget", {})
        self.max_calls = int(b.get("max_model_calls", 8))
        self.deadline = time.monotonic() + float(b.get("review_timeout_s", 600))
        self.calls = {"total": 0, "cached": 0, "failed": 0}
        self.infra_errors: list[str] = []
        self.parse_stats: list[dict] = []
        r = profile.get("retry", {})
        self.retry = dict(
            attempts=int(r.get("attempts", 3)), base_delay_s=float(r.get("base_delay_s", 1)), max_delay_s=float(r.get("max_delay_s", 8))
        )
        c = profile.get("cache", {})
        self.cache = CompletionCache(c.get("dir", ".acr-cache"), audit, enabled=bool(c.get("enabled", True)))


def _breaker(ctx: ReviewContext, adapter: ModelAdapter) -> CircuitBreaker:
    c = ctx.profile.get("circuit", {})
    return CircuitBreaker.for_key(adapter.endpoint, int(c.get("failure_threshold", 3)), float(c.get("cooldown_s", 60)))


def _generate(ctx: ReviewContext, adapter: ModelAdapter, req: GenerationRequest, model_digest: str | None) -> str:
    key = key_for(
        wrapper=adapter.endpoint,
        model=req.model,
        digest=model_digest,
        system=req.system,
        prompt=req.prompt,
        t=req.temperature,
        seed=req.seed,
        n=req.max_tokens,
        ctx=req.num_ctx,
        raw=req.raw,
    )
    cached = ctx.cache.get(key)
    ctx.calls["total"] += 1
    if cached is not None:
        ctx.calls["cached"] += 1
        return cached
    remaining = ctx.deadline - time.monotonic()
    if remaining <= 0:
        ctx.audit.record("review_deadline_exceeded", op="generate", model=req.model)
        raise AdapterError("review deadline exceeded")
    req.timeout_s = min(req.timeout_s, remaining)
    completion = call_with_retry(
        lambda: adapter.generate(req),
        **ctx.retry,
        deadline=ctx.deadline,
        breaker=_breaker(ctx, adapter),
        audit=ctx.audit,
        op=f"generate:{req.model}",
    )
    ctx.cache.put(key, completion.text)
    return completion.text


def _prepare_runtime(ctx: ReviewContext, routes: list[router.Route]) -> tuple[ModelAdapter | None, dict[str, str | None]]:
    """Health-check the runtime, verify model integrity, optionally pull models. Returns adapter + digests."""
    runtime = ctx.profile.get("runtime", {})
    wanted = [r for r in routes if r.model]
    if not wanted:
        return None, {}
    try:
        adapter = load_adapter(runtime.get("wrapper", "ollama"), runtime, ctx.root)
        health = call_with_retry(
            lambda: _health_or_raise(adapter),
            **ctx.retry,
            deadline=ctx.deadline,
            breaker=_breaker(ctx, adapter),
            audit=ctx.audit,
            op="health",
        )
    except (AdapterError, KeyError, ValueError) as e:
        ctx.infra_errors.append(f"model runtime unavailable: {e}")
        ctx.audit.record("fallback_rules_only", reason=str(e))
        for r in wanted:
            r.reason, r.model = f"rules-only: runtime unavailable ({e})", None
        return None, {}
    available = {m.get("name"): m.get("digest") for m in health.models} | {m.get("model"): m.get("digest") for m in health.models}
    digests: dict[str, str | None] = {}
    for r in wanted:
        m = r.model
        if available and m.ref not in available and runtime.get("auto_pull", False) and hasattr(adapter, "pull"):
            try:
                ctx.audit.record("model_pull", model=m.ref)
                call_with_retry(
                    lambda ref=m.ref: adapter.pull(ref),
                    **ctx.retry,
                    deadline=ctx.deadline,
                    breaker=None,
                    audit=ctx.audit,
                    op=f"pull:{m.ref}",
                )
                available = {x.get("name"): x.get("digest") for x in adapter.health().models}
            except AdapterError as e:
                ctx.audit.record("model_pull_failed", model=m.ref, error=str(e))
        digest = available.get(m.ref)
        if m.digest and digest and not digest.startswith(m.digest.removeprefix("sha256:")):
            ctx.audit.record("model_integrity_mismatch", model=m.ref, expected=m.digest, actual=digest)
            ctx.infra_errors.append(f"{m.ref}: digest mismatch")
            r.reason, r.model = "rules-only: model digest mismatch", None
            continue
        digests[m.ref] = digest
    return adapter, digests


def _health_or_raise(adapter: ModelAdapter):
    h = adapter.health()
    if not h.ok:
        raise AdapterError(h.detail, transient=True)
    return h


def _model_findings(
    ctx: ReviewContext, adapter: ModelAdapter, route: router.Route, files: list[diffmod.FileDiff], digest: str | None, skipped: list[str]
) -> list[Finding]:
    gen = ctx.profile.get("generation", {})
    relevant = [f for f in files if any(f.matches(s.file_globs, s.languages, s.exclude_globs) for s in route.skills)]
    max_chars = int(ctx.profile.get("budget", {}).get("max_diff_chars", 24000))
    chunks, too_big = diffmod.chunk(relevant, max_chars)
    skipped.extend(p for p in too_big if p not in skipped)
    if len(chunks) > ctx.max_calls - ctx.calls["total"]:
        dropped = chunks[max(0, ctx.max_calls - ctx.calls["total"]) :]
        ctx.audit.record("budget_limited", tier=route.tier, dropped_chunks=len(dropped))
        skipped.extend(f.path for c in dropped for f in c)
        chunks = chunks[: max(0, ctx.max_calls - ctx.calls["total"])]
    m = route.model

    def one(chunk: list[diffmod.FileDiff]) -> list[Finding]:
        system, user = prompt.build(route.skills, diffmod.render(chunk))
        req = GenerationRequest(
            model=m.ref_for(ctx.profile.get("runtime", {}).get("wrapper", "ollama")),
            prompt=user,
            system=system,
            temperature=gen.get("temperature", 0.0),
            seed=gen.get("seed", 42),
            max_tokens=gen.get("max_tokens", 1024),
            num_ctx=gen.get("num_ctx"),
            timeout_s=float(ctx.profile.get("budget", {}).get("call_timeout_s", 120)),
            json_mode=gen.get("json_mode", True),
        )
        try:
            text = _generate(ctx, adapter, req, digest)
        except AdapterError as e:
            ctx.calls["failed"] += 1
            ctx.infra_errors.append(f"{m.ref}: {e}")
            ctx.audit.record("chunk_skipped_model_failure", model=m.ref, files=[f.path for f in chunk])
            return []
        found, stats = parse.to_findings(text, route.skills, chunk, m.id)
        ctx.parse_stats.append({"model": m.id, **stats})
        return found

    workers = max(1, int(ctx.profile.get("budget", {}).get("concurrency", 1)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return [f for batch in pool.map(one, chunks) for f in batch]


def merge(findings: list[Finding]) -> list[Finding]:
    """Deduplicate. A model finding that hits a rule finding's line+category corroborates it."""
    out: list[Finding] = []
    seen: dict[tuple, Finding] = {}
    for f in sorted(findings, key=lambda x: (x.source != "rule", x.location.path, x.location.start_line, x.rule_id)):
        exact = (f.rule_id, f.location.path, f.location.start_line)
        near = (f.category, f.location.path, f.location.start_line)
        if exact in seen:
            continue
        if f.source == "model" and near in seen and seen[near].source == "rule":
            seen[near].corroborated_by.append(f"{f.model}:{f.rule_id}")
            continue
        seen[exact] = f
        seen.setdefault(near, f)
        out.append(f)
    order = {s: i for i, s in enumerate(reversed(SEVERITIES))}
    return sorted(out, key=lambda x: (order[x.severity], x.location.path, x.location.start_line, x.rule_id))


def run_review(
    diff_text: str,
    profile_name: str = "balanced",
    policy_name: str | None = None,
    revision: str | None = None,
    repository: str | None = None,
    audit: Audit | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    root = root or cfg.home()
    audit = audit or Audit()
    started = dt.datetime.now(dt.UTC)
    t0 = time.monotonic()
    profile = cfg.env_overrides(cfg.load_profile(profile_name, root))
    policy = cfg.load_policy(policy_name or profile.get("policy", "default"), root)
    ctx = ReviewContext(profile, policy, audit, root)
    all_skills = cfg.load_skills(root)
    skills = cfg.select_skills(profile.get("skills", ["*"]), all_skills)
    models = cfg.load_models(root)
    files = diffmod.parse(diff_text)
    max_files = int(profile.get("budget", {}).get("max_files", 200))
    skipped = [f.path for f in files[max_files:]]
    files = files[:max_files]

    legacy_raw = None
    findings: list[Finding] = []
    routes: list[router.Route] = []
    if profile.get("mode") == "legacy":
        legacy_raw = _legacy(ctx, skills, diff_text, models)
    else:
        if profile.get("rules", {}).get("enabled", True):
            for s in skills:
                findings += run_rules(s, files) + run_companions(s, files)
        routes = router.plan(skills, profile, models, policy)
        if files and profile.get("routing", {}).get("tiers"):
            for r in routes:
                if r.model is None:  # a model was intended but could not be used: degraded, never silent
                    ctx.infra_errors.append(f"{r.tier} tier: {r.reason}")
        if files:
            adapter, digests = _prepare_runtime(ctx, routes)
            for r in routes:
                if adapter and r.model:
                    findings += _model_findings(ctx, adapter, r, files, digests.get(r.model.ref), skipped)
        findings = merge(findings)
    baseline_file = policy.get("baseline", {}).get("file")
    gate.apply_baseline(findings, gate.load_baseline(root / baseline_file if baseline_file else None), audit)
    g = gate.evaluate(findings, policy, ctx.infra_errors)
    if legacy_raw is not None:
        g = _legacy_gate(ctx, legacy_raw)

    used = {r.model.id: r.model for r in routes if r.model}
    fdicts = [f.to_dict() for f in findings]
    return {
        "schema": RESULT_SCHEMA,
        "tool": {"name": "ai-code-reviewers", "version": __version__},
        "run": {
            "id": str(uuid.uuid4()),
            "started_at": started.isoformat(timespec="seconds"),
            "duration_ms": int((time.monotonic() - t0) * 1000),
            "profile": profile.get("id", profile_name),
            "policy": {"id": policy.get("id", "default"), "version": policy.get("version", "0")},
            "revision": revision,
            "repository": repository,
            "source": {
                "files_reviewed": len(files),
                "files_skipped": sorted(set(skipped)),
                "added_lines": sum(len(f.added) for f in files),
            },
            "skills": [{"id": s.id, "version": s.version} for s in skills],
            "models": [
                {"id": m.id, "ref": m.ref, "tier": m.tier, "status": m.status, "license": m.license, "digest": m.digest or None}
                for m in used.values()
            ],
            "routing": [r.to_dict() for r in routes],
            "calls": ctx.calls,
            "parse": ctx.parse_stats,
            "degraded": bool(ctx.infra_errors),
            "infrastructure_errors": ctx.infra_errors,
            "recovery_events": audit.events,
            "legacy_raw_output": legacy_raw,
        },
        "findings": fdicts,
        "summary": {
            "total": len(fdicts),
            "by_severity": {s: sum(1 for f in fdicts if f["severity"] == s) for s in reversed(SEVERITIES)},
            "by_source": {s: sum(1 for f in fdicts if f["source"] == s) for s in ("rule", "model")},
            "verified": sum(1 for f in fdicts if f["kind"] == "verified"),
        },
        "gate": g,
    }


# --- legacy mode: behaviour-compatible with Firefly's ReviewGate.java -------------------


def _legacy(ctx: ReviewContext, skills: list[cfg.Skill], diff_text: str, models) -> str | None:
    skill = next((s for s in skills if s.output == "legacy-severity"), None)
    model_ref = ctx.profile.get("routing", {}).get("small_model", "")
    if skill is None or not model_ref.strip():
        ctx.infra_errors.append("No model: set LLM_MODEL or pass --model <model-id>")
        return None
    if not diff_text.strip():
        return "SEVERITY: NONE\nSUMMARY: empty diff, nothing to review"
    runtime = ctx.profile.get("runtime", {})
    try:
        adapter = load_adapter(runtime.get("wrapper", "ollama"), runtime, ctx.root)
        req = GenerationRequest(
            model=model_ref,
            prompt=prompt.build_legacy(skill, diff_text),
            raw=True,
            timeout_s=float(ctx.profile.get("budget", {}).get("call_timeout_s", 120)),
        )
        return _generate(ctx, adapter, req, None)
    except AdapterError as e:
        ctx.infra_errors.append(f"Could not reach the model runtime: {e}")
        return None


def _legacy_gate(ctx: ReviewContext, raw: str | None) -> dict:
    if raw is None:
        return {
            "status": "error",
            "exit_code": 2,
            "legacy_severity": "NONE",
            "reasons": ctx.infra_errors,
            "blocking_findings": 0,
            "suppressed_findings": 0,
        }
    sev = parse.legacy_severity(raw)
    status = {"BLOCK": "block", "MINOR": "warn"}.get(sev, "pass")
    return {
        "status": status,
        "exit_code": 1 if sev == "BLOCK" else 0,
        "legacy_severity": sev,
        "reasons": [],
        "blocking_findings": int(sev == "BLOCK"),
        "suppressed_findings": 0,
    }
