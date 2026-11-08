import json

import pytest

from orchestrator.contracts import AdapterError
from orchestrator.recovery.audit import Audit
from orchestrator.recovery.cache import CompletionCache, key_for
from orchestrator.recovery.retry import CircuitBreaker, CircuitOpen, call_with_retry


def audit():
    return Audit(open("/dev/null", "w"))


def test_transient_errors_are_retried_with_backoff_then_succeed():
    calls, sleeps, a = [], [], audit()

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise AdapterError("503", transient=True)
        return "ok"

    assert (
        call_with_retry(fn, attempts=3, base_delay_s=1, max_delay_s=1.5, deadline=None, breaker=None, audit=a, op="x", sleep=sleeps.append)
        == "ok"
    )
    assert sleeps == [1, 1.5] and [e["action"] for e in a.events] == ["retry", "retry"]


def test_permanent_errors_are_not_retried():
    a = audit()
    with pytest.raises(AdapterError):
        call_with_retry(
            lambda: (_ for _ in ()).throw(AdapterError("400")),
            attempts=5,
            base_delay_s=0,
            max_delay_s=0,
            deadline=None,
            breaker=None,
            audit=a,
            op="x",
            sleep=lambda s: None,
        )
    assert [e["action"] for e in a.events] == ["permanent_failure"]


def test_retry_is_bounded():
    n = []

    def fn():
        n.append(1)
        raise AdapterError("down", transient=True)

    with pytest.raises(AdapterError):
        call_with_retry(
            fn, attempts=4, base_delay_s=0, max_delay_s=0, deadline=None, breaker=None, audit=audit(), op="x", sleep=lambda s: None
        )
    assert len(n) == 4


def test_circuit_opens_then_half_opens_after_cooldown():
    now = [0.0]
    cb = CircuitBreaker("k", threshold=2, cooldown_s=10, clock=lambda: now[0])
    cb.failure()
    cb.before()
    cb.failure()
    with pytest.raises(CircuitOpen):
        cb.before()
    now[0] = 11
    assert cb.state == "half-open"
    cb.before()
    cb.failure()  # a failure while half-open re-opens immediately
    assert cb.state == "open"
    now[0] = 30
    cb.before()
    cb.success()
    assert cb.state == "closed"


def test_cache_roundtrip_and_corruption_self_heals(tmp_path):
    a = audit()
    c = CompletionCache(tmp_path, a)
    k = key_for(prompt="p", model="m")
    assert c.get(k) is None
    c.put(k, "hello")
    assert c.get(k) == "hello"
    path = next(tmp_path.rglob("*.json"))
    entry = json.loads(path.read_text())
    entry["text"] = "tampered"
    path.write_text(json.dumps(entry))
    assert c.get(k) is None and not path.exists()
    assert a.events[-1]["action"] == "cache_entry_evicted"


def test_cache_key_depends_on_every_input():
    assert key_for(a=1, b=2) == key_for(b=2, a=1)
    assert key_for(a=1, digest="x") != key_for(a=1, digest="y")
