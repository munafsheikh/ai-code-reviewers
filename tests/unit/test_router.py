from orchestrator import config as cfg
from orchestrator.routing import router

SKILLS = cfg.load_skills()
MODELS = cfg.load_models()
SEL = [SKILLS["security.injection"], SKILLS["architecture.design"]]


def profile(**routing):
    p = cfg.load_profile("deep")
    p["routing"].update(routing)
    return p


def test_deep_routes_small_and_large():
    routes = router.plan(SEL, profile(), MODELS, {})
    assert [(r.tier, r.model.id) for r in routes] == [("small", "qwen2.5-coder-1.5b"), ("large", "qwen2.5-coder-7b")]


def test_large_downgrades_to_small_when_over_memory_budget():
    p = profile()
    p["budget"]["memory_budget_mb"] = 4096
    routes = router.plan(SEL, p, MODELS, {})
    assert len(routes) == 1 and routes[0].model.id == "qwen2.5-coder-1.5b"
    assert "architecture.design" in [s.id for s in routes[0].skills] and "downgraded" in routes[0].reason


def test_no_fallback_means_rules_only():
    p = profile(fallback=["rules"])
    p["budget"]["memory_budget_mb"] = 4096
    large = [r for r in router.plan(SEL, p, MODELS, {}) if r.tier == "large"][0]
    assert large.model is None and large.reason.startswith("rules-only")


def test_policy_requiring_pinned_models_rejects_unpinned():
    routes = router.plan(SEL, profile(), MODELS, {"models": {"require_pinned": True}})
    assert all(r.model is None for r in routes)


def test_unregistered_runtime_ref_is_allowed_but_marked():
    (r,) = router.plan(SEL[:1], profile(small_model="some/custom:3b"), MODELS, {})
    assert r.model.ref == "some/custom:3b" and r.model.status == "unregistered"
