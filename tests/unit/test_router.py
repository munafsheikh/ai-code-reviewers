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


def test_policy_license_classes_gate_models():
    p = profile(small_model="codestral-22b")
    p["budget"]["memory_budget_mb"] = 65536
    default = cfg.load_policy("default")
    (r,) = router.plan(SEL[:1], p, MODELS, default)
    assert r.model is None and "non-production" in r.reason
    evaluation = cfg.load_policy("evaluation")
    (r,) = router.plan(SEL[:1], p, MODELS, evaluation)
    assert r.model.id == "codestral-22b"
    p["routing"]["small_model"] = "llama3.2-3b"
    assert router.plan(SEL[:1], p, MODELS, default)[0].model.id == "llama3.2-3b"
    assert (
        router.plan(SEL[:1], p, MODELS, cfg.load_policy("strict") | {"models": {"allowed_license_classes": ["permissive"]}})[0].model
        is None
    )


def test_runtime_specific_model_names():
    m = MODELS["qwen3-coder-30b-a3b"]
    assert m.ref_for("ollama") == "qwen3-coder:30b"
    assert m.ref_for("llama-cpp") == "Qwen/Qwen3-Coder-30B-A3B-Instruct"


def test_catalog_is_consistent():
    assert len(MODELS) >= 15
    for m in MODELS.values():
        assert m.kind in ("code-instruct", "instruct", "reasoning")
        assert m.raw.get("evidence"), m.id
        assert (m.tier == "small") == (m.params_b < 6), m.id
        if m.license_class == "permissive":
            assert m.license in ("Apache-2.0", "MIT"), m.id


def test_empty_model_env_does_not_disable_the_profile_model(monkeypatch):
    """Regression: CI forwarded an unset LLM_MODEL as "", which routed rules-only."""
    monkeypatch.setenv("LLM_MODEL", "")
    p = cfg.env_overrides(cfg.load_profile("balanced"))
    assert p["routing"]["small_model"] == "qwen2.5-coder-1.5b"
    monkeypatch.setenv("ACR_SMALL_MODEL", "  ")
    assert cfg.env_overrides(cfg.load_profile("balanced"))["routing"]["small_model"] == "qwen2.5-coder-1.5b"
    # The legacy profile keeps ReviewGate semantics: empty means "no model" (exit 2, golden-tested).
    monkeypatch.delenv("ACR_SMALL_MODEL")
    assert cfg.env_overrides(cfg.load_profile("legacy"))["routing"]["small_model"] == ""
