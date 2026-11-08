"""acr.wrapper/v1 contract: every wrapper honours health/generate semantics and its declared permissions."""

import sys

import pytest

from orchestrator import config as cfg
from orchestrator.cli.validate import check_wrapper_permissions
from orchestrator.contracts import AdapterError, Completion, GenerationRequest, ModelAdapter
from orchestrator.engine.adapters import load_adapter


@pytest.mark.parametrize("wrapper", ["ollama", "llama-cpp"])
def test_http_wrappers_against_fake_runtime(runtime, monkeypatch, wrapper):
    monkeypatch.setenv("FAKE_RESPONSE_TEXT", '{"findings": []}')
    a = load_adapter(wrapper, {"base_url": runtime})
    assert isinstance(a, ModelAdapter) and a.health().ok
    c = a.generate(GenerationRequest(model="m", prompt="p", system="s"))
    assert isinstance(c, Completion) and c.text == '{"findings": []}' and c.latency_ms >= 0


@pytest.mark.parametrize("wrapper", ["ollama", "llama-cpp"])
def test_http_wrappers_classify_errors(runtime, monkeypatch, wrapper):
    monkeypatch.setenv("FAKE_FAIL_FIRST_N", "1")
    a = load_adapter(wrapper, {"base_url": runtime})
    with pytest.raises(AdapterError) as e:
        a.generate(GenerationRequest(model="m", prompt="p"))
    assert e.value.transient  # 503 is retryable
    down = load_adapter(wrapper, {"base_url": "http://127.0.0.1:9"})
    assert not down.health().ok


def test_egress_allowlist_blocks_external_hosts():
    a = load_adapter("ollama", {"base_url": "https://inference.example.com"})
    with pytest.raises(AdapterError, match="not allowed"):
        a.generate(GenerationRequest(model="m", prompt="p"))
    assert "not allowed" in a.health().detail


def test_cli_wrapper_uses_argv_without_shell():
    cmd = [sys.executable, "-c", "import sys; sys.stdout.write('{\"findings\": []}' if sys.stdin.read() else 'x')"]
    a = load_adapter("cli", {"command": cmd})
    assert a.health().ok
    assert a.generate(GenerationRequest(model="m", prompt="p")).text == '{"findings": []}'
    bad = load_adapter("cli", {"command": [sys.executable, "-c", "import sys; sys.exit(3)"]})
    with pytest.raises(AdapterError, match="exited 3"):
        bad.generate(GenerationRequest(model="m", prompt="p"))
    assert not load_adapter("cli", {"command": []}).health().ok


def test_reference_wrapper():
    a = load_adapter("example-echo", {})
    assert a.health().ok and a.model_digest("echo") == "0" * 64


def test_every_wrapper_manifest_matches_its_code():
    for mf in (cfg.home() / "wrappers").rglob("wrapper.toml"):
        d = cfg.load_toml(mf)
        src = (mf.parent / d["entrypoint"].split(":")[0]).read_text()
        assert check_wrapper_permissions(d, src) == [], mf


def test_permission_checker_detects_violations():
    m = {"permissions": {"network": "none", "subprocess": False, "filesystem": "none"}}
    assert check_wrapper_permissions(m, "import subprocess")
    assert check_wrapper_permissions(m, "import os\nos.system('x')")
    assert check_wrapper_permissions(m, "from orchestrator.engine.http import request_json")
    assert check_wrapper_permissions(m, "open('x')")
    allow = {"permissions": {"network": "allowlist", "subprocess": False, "filesystem": "none"}}
    assert check_wrapper_permissions(allow, "import urllib.request")
    assert check_wrapper_permissions(allow, "from orchestrator.engine.http import request_json") == []
