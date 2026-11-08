"""Model routing: which model (if any) serves each skill tier.

Decision inputs: the skill's declared tier, the profile's enabled tiers and
fallback chain, the memory budget vs. the model manifest, model integrity
(pinned digests) and runtime health. Every decision is recorded.
"""

from __future__ import annotations

from dataclasses import dataclass

from orchestrator.config import ModelManifest, Skill, resolve_model


@dataclass
class Route:
    tier: str
    skills: list[Skill]
    model: ModelManifest | None
    reason: str

    def to_dict(self) -> dict:
        return {
            "tier": self.tier,
            "skills": [s.id for s in self.skills],
            "model": self.model.id if self.model else None,
            "reason": self.reason,
        }


def _candidate(tier: str, profile: dict, models: dict[str, ModelManifest], policy: dict) -> tuple[ModelManifest | None, str]:
    routing = profile.get("routing", {})
    if tier not in routing.get("tiers", []):
        return None, f"tier '{tier}' disabled by profile"
    name = routing.get(f"{tier}_model", "")
    if not name:
        return None, f"no {tier}_model configured"
    m = resolve_model(name, models, tier)
    budget = profile.get("budget", {}).get("memory_budget_mb", 0)
    if budget and m.min_ram_mb > budget:
        return None, f"{m.id} needs {m.min_ram_mb}MB > budget {budget}MB"
    if policy.get("models", {}).get("require_pinned", False) and not m.digest:
        return None, f"{m.id} has no pinned digest and policy requires one"
    if m.status in policy.get("models", {}).get("forbidden_status", ["rejected"]):
        return None, f"{m.id} status '{m.status}' is not allowed"
    return m, "selected"


def plan(skills: list[Skill], profile: dict, models: dict[str, ModelManifest], policy: dict) -> list[Route]:
    routes: list[Route] = []
    prompted = [s for s in skills if s.prompt and s.tier in ("small", "large")]
    fallback = profile.get("routing", {}).get("fallback", ["small", "rules"])
    for tier in ("small", "large"):
        group = [s for s in prompted if s.tier == tier]
        if not group:
            continue
        model, why = _candidate(tier, profile, models, policy)
        if model is None and tier == "large" and "small" in fallback:
            model, why2 = _candidate("small", profile, models, policy)
            why = f"{why}; downgraded to small" + ("" if model else f" ({why2})")
            if model:
                # Merge into an existing small route if present to save a model call.
                existing = next((r for r in routes if r.model and r.model.id == model.id), None)
                if existing:
                    existing.skills.extend(group)
                    existing.reason += f"; +large skills ({why})"
                    continue
        routes.append(Route(tier, group, model, why if model else f"rules-only: {why}"))
    return routes
