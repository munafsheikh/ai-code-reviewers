import os
import threading
from pathlib import Path

import pytest

from orchestrator.recovery.retry import CircuitBreaker
from tests.support import fake_runtime

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "benchmarks" / "fixtures"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    for var in [v for v in os.environ if v.startswith(("ACR_", "LLM_", "FAKE_"))]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ACR_CACHE_DIR", str(tmp_path / "cache"))
    CircuitBreaker._registry.clear()
    fake_runtime._calls["inference"] = 0
    yield


@pytest.fixture
def runtime(monkeypatch):
    """In-process fake model runtime; returns its base URL and points ACR_MODEL_HOST at it."""
    monkeypatch.setenv("FAKE_LOCAL_ONLY", "1")
    srv = fake_runtime.serve(0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    monkeypatch.setenv("ACR_MODEL_HOST", url)
    yield url
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def fast_retry(monkeypatch, tmp_path):
    """A profile identical to balanced but with near-zero retry delays."""
    p = tmp_path / "profile.toml"
    p.write_text('extends = "balanced"\nid = "test"\n[retry]\nattempts = 3\nbase_delay_s = 0.01\nmax_delay_s = 0.02\n')
    return str(p)


def fixture_diff(name: str) -> str:
    return (FIXTURES / name / "diff.patch").read_text()
