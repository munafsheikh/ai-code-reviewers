"""HTTP review service (stdlib only).

GET  /healthz    liveness (process up)
GET  /readyz     readiness (runtime reachable, or rules-only fallback available)
GET  /metrics    Prometheus text format
POST /v1/review  body: raw unified diff (text/plain) or {"diff": "...", "profile": "...", "format": "json|sarif|markdown|legacy"}
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from orchestrator import config as cfg
from orchestrator import schema
from orchestrator.engine import report
from orchestrator.engine.review import run_review
from orchestrator.recovery.audit import Audit

MAX_BODY = int(os.environ.get("ACR_MAX_BODY_BYTES", str(2 * 1024 * 1024)))
# Oversized bodies are read and discarded up to this cap so the client receives the 413
# instead of a broken pipe; anything larger is cut off by closing the connection.
MAX_DRAIN = int(os.environ.get("ACR_MAX_DRAIN_BYTES", str(32 * 1024 * 1024)))
MAX_CONCURRENT = int(os.environ.get("ACR_MAX_CONCURRENT_REVIEWS", "2"))
ALLOWED_PROFILES = set(os.environ.get("ACR_ALLOWED_PROFILES", "fast,balanced,deep,offline").split(","))

_slots = threading.BoundedSemaphore(MAX_CONCURRENT)
_metrics = {
    "reviews_total": 0,
    "reviews_failed_total": 0,
    "reviews_degraded_total": 0,
    "reviews_rejected_total": 0,
    "findings_total": 0,
    "review_duration_ms_sum": 0,
    "recovery_events_total": 0,
}
_mlock = threading.Lock()
_started = time.time()


def _inc(**kv: int) -> None:
    with _mlock:
        for k, v in kv.items():
            _metrics[k] += v


class Handler(BaseHTTPRequestHandler):
    server_version = "acr"
    default_profile = "balanced"

    def log_message(self, fmt, *args):
        print(json.dumps({"level": "info", "component": "http", "msg": fmt % args}), file=sys.stderr)

    def _send(self, code: int, body: str | bytes, ctype: str = "application/json") -> None:
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def _drain(self, n: int) -> None:
        remaining = min(n, MAX_DRAIN)
        while remaining > 0:
            chunk = self.rfile.read(min(65536, remaining))
            if not chunk:
                break
            remaining -= len(chunk)

    def do_GET(self):
        if self.path == "/healthz":
            self._send(200, json.dumps({"status": "ok", "uptime_s": int(time.time() - _started)}))
        elif self.path == "/readyz":
            self._send(200, json.dumps(readiness(self.default_profile)))
        elif self.path == "/metrics":
            with _mlock:
                lines = [f"acr_{k} {v}" for k, v in _metrics.items()]
            self._send(200, "\n".join(lines) + "\n", "text/plain; version=0.0.4")
        else:
            self._send(404, '{"error":"not found"}')

    def do_POST(self):
        if self.path != "/v1/review":
            return self._send(404, '{"error":"not found"}')
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BODY:
            _inc(reviews_rejected_total=1)
            self.close_connection = True
            if n > MAX_BODY:
                self._drain(n)
            return self._send(413 if n > MAX_BODY else 400, json.dumps({"error": f"body must be 1..{MAX_BODY} bytes"}))
        raw = self.rfile.read(n).decode("utf-8", errors="replace")
        profile, fmt, diff_text = self.default_profile, "json", raw
        if (self.headers.get("Content-Type") or "").startswith("application/json"):
            try:
                body = json.loads(raw)
                diff_text = body["diff"]
                profile = body.get("profile", profile)
                fmt = body.get("format", fmt)
            except (json.JSONDecodeError, KeyError, TypeError):
                return self._send(400, '{"error":"expected {\\"diff\\": \\"...\\"}"}')
        if profile not in ALLOWED_PROFILES or fmt not in report.RENDERERS:
            return self._send(400, json.dumps({"error": "profile or format not allowed"}))
        if not _slots.acquire(blocking=False):
            _inc(reviews_rejected_total=1)
            return self._send(429, '{"error":"too many concurrent reviews"}')
        try:
            result = run_review(diff_text, profile, audit=Audit())
            errs = schema.validate(result, schema.load("review-result"))
            if errs:
                raise RuntimeError(f"result failed schema validation: {errs[:3]}")
        except Exception as e:  # noqa: BLE001 - report, never crash the service
            _inc(reviews_total=1, reviews_failed_total=1)
            return self._send(500, json.dumps({"error": type(e).__name__, "detail": str(e)[:300]}))
        finally:
            _slots.release()
        _inc(
            reviews_total=1,
            findings_total=len(result["findings"]),
            reviews_degraded_total=int(result["run"]["degraded"]),
            review_duration_ms_sum=result["run"]["duration_ms"],
            recovery_events_total=len(result["run"]["recovery_events"]),
        )
        ctype = {"json": "application/json", "sarif": "application/sarif+json"}.get(fmt, "text/plain; charset=utf-8")
        self._send(200, report.RENDERERS[fmt](result), ctype)


def readiness(profile_name: str) -> dict:
    from orchestrator.engine.adapters import load_adapter

    profile = cfg.env_overrides(cfg.load_profile(profile_name))
    if not profile.get("routing", {}).get("tiers"):
        return {"status": "ready", "mode": "rules-only"}
    try:
        h = load_adapter(profile["runtime"]["wrapper"], profile["runtime"]).health()
    except Exception as e:  # noqa: BLE001
        h = type("H", (), {"ok": False, "detail": str(e), "models": []})()
    names = {m.get("name") for m in h.models} | {m.get("model") for m in h.models}
    wanted = [
        cfg.resolve_model(profile["routing"].get(f"{t}_model", ""), cfg.load_models(), t).ref
        for t in profile["routing"]["tiers"]
        if profile["routing"].get(f"{t}_model")
    ]
    missing = [w for w in wanted if names and w not in names] if profile["runtime"].get("wrapper") == "ollama" else []
    if h.ok and not h.models and profile["runtime"].get("wrapper") == "ollama":
        missing = wanted
    # Rules-only fallback keeps the service useful, so readiness reports degraded rather than failing.
    status = "ready" if h.ok and not missing else "degraded"
    return {"status": status, "runtime_ok": h.ok, "detail": h.detail, "missing_models": missing, "models": sorted(n for n in names if n)}


def main(host: str, port: int, profile: str) -> int:
    Handler.default_profile = profile
    srv = ThreadingHTTPServer((host, port), Handler)
    print(
        json.dumps({"level": "info", "component": "http", "msg": f"listening on {host}:{port}", "profile": profile}),
        file=sys.stderr,
        flush=True,
    )
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print(json.dumps({"level": "info", "component": "http", "msg": "shutting down"}), file=sys.stderr)
    finally:
        srv.server_close()
    return 0
