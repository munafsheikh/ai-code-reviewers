"""Bounded retry with exponential backoff, plus a per-endpoint circuit breaker."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TypeVar

from orchestrator.contracts import AdapterError
from orchestrator.recovery.audit import Audit

T = TypeVar("T")


class CircuitOpen(AdapterError):
    def __init__(self, key: str, retry_in: float):
        super().__init__(f"circuit open for {key}; retry in {retry_in:.0f}s", transient=False)


class CircuitBreaker:
    """closed -> open after N consecutive failures -> half-open after cooldown -> closed on success."""

    _registry: dict[str, CircuitBreaker] = {}
    _lock = threading.Lock()

    def __init__(self, key: str, threshold: int = 3, cooldown_s: float = 60.0, clock=time.monotonic):
        self.key, self.threshold, self.cooldown_s, self.clock = key, threshold, cooldown_s, clock
        self.failures = 0
        self.opened_at: float | None = None

    @classmethod
    def for_key(cls, key: str, threshold: int, cooldown_s: float) -> CircuitBreaker:
        with cls._lock:
            cb = cls._registry.get(key)
            if cb is None:
                cb = cls._registry[key] = cls(key, threshold, cooldown_s)
            return cb

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        return "half-open" if self.clock() - self.opened_at >= self.cooldown_s else "open"

    def before(self) -> None:
        if self.state == "open":
            raise CircuitOpen(self.key, self.cooldown_s - (self.clock() - (self.opened_at or 0)))

    def success(self) -> None:
        self.failures, self.opened_at = 0, None

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold or self.state == "half-open":
            self.opened_at = self.clock()


def call_with_retry(
    fn: Callable[[], T],
    *,
    attempts: int,
    base_delay_s: float,
    max_delay_s: float,
    deadline: float | None,
    breaker: CircuitBreaker | None,
    audit: Audit,
    op: str,
    sleep=time.sleep,
) -> T:
    attempts = max(1, attempts)
    last: AdapterError | None = None
    for n in range(1, attempts + 1):
        if breaker:
            breaker.before()
        try:
            result = fn()
        except AdapterError as e:
            last = e
            if breaker:
                breaker.failure()
            if not e.transient or n == attempts:
                audit.record("retry_exhausted" if e.transient else "permanent_failure", op=op, attempt=n, error=str(e))
                raise
            delay = min(max_delay_s, base_delay_s * 2 ** (n - 1))
            if deadline is not None and time.monotonic() + delay > deadline:
                audit.record("retry_abandoned_deadline", op=op, attempt=n, error=str(e))
                raise
            audit.record("retry", op=op, attempt=n, delay_s=delay, error=str(e))
            sleep(delay)
        else:
            if breaker:
                breaker.success()
            return result
    raise last  # pragma: no cover
