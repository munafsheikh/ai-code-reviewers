"""Deterministic stand-in for a local model runtime (Ollama + llama.cpp APIs).

Used by contract, integration, regression and end-to-end tests so the full
HTTP path can be exercised without downloading model weights.

Behaviour is controlled by environment variables:
  FAKE_PORT            listen port (default 11434)
  FAKE_RESPONSE_TEXT   fixed completion text for every generate/chat call
  FAKE_FAIL_FIRST_N    return HTTP 503 for the first N inference calls
  FAKE_DELAY_SECONDS   sleep before answering inference calls
  FAKE_MODELS          comma-separated model ids reported by /api/tags
  FAKE_RECORD_FILE     append every POST body (JSON lines) to this file

Without FAKE_RESPONSE_TEXT the runtime answers with a JSON findings array
derived from simple keyword matches in the prompt's DIFF section, which is
enough to exercise parsing, merging and gating.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_lock = threading.Lock()
_calls = {"inference": 0}

SCRIPTED = [
    (re.compile(r"catch\s*\([^)]*\)\s*\{\s*\}"), "major", "Swallowed exception hides failures"),
    (re.compile(r"\"\s*\+\s*\w+\s*\+\s*\"?.*(SELECT|INSERT|UPDATE|DELETE)", re.I), "critical", "SQL built by string concatenation"),
    (re.compile(r"(SELECT|INSERT|UPDATE|DELETE)[^\n]*\"\s*\+", re.I), "critical", "SQL built by string concatenation"),
]


def _scripted_findings(prompt: str) -> str:
    diff = prompt.split("<untrusted_diff>", 1)[-1]
    findings = []
    path, new_line = None, 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            path = raw[4:].removeprefix("b/").strip()
            continue
        m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", raw)
        if m:
            new_line = int(m.group(1))
            continue
        if raw.startswith("+"):
            for rx, sev, title in SCRIPTED:
                if rx.search(raw):
                    findings.append(
                        {
                            "path": path,
                            "line": new_line,
                            "severity": sev,
                            "title": title,
                            "explanation": f"{title}.",
                            "evidence": raw[1:].strip()[:200],
                            "remediation": "Handle or propagate the error / use parameterised queries.",
                            "confidence": "medium",
                        }
                    )
            new_line += 1
        elif not raw.startswith("-"):
            new_line += 1
    return json.dumps({"findings": findings})


class Handler(BaseHTTPRequestHandler):
    server_version = "fake-runtime/1.0"

    def log_message(self, fmt, *args):  # keep test output quiet
        if os.environ.get("FAKE_VERBOSE"):
            sys.stderr.write(fmt % args + "\n")

    def _send(self, code: int, payload) -> None:
        # Compact separators match Go encoding/json (what Ollama emits).
        body = payload if isinstance(payload, bytes) else json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return {}

    def do_GET(self):
        if self.path in ("/", "/health"):
            self._send(200, b"Ollama is running")
        elif self.path == "/api/tags":
            models = [m for m in os.environ.get("FAKE_MODELS", "qwen2.5-coder:0.5b,qwen2.5-coder:1.5b").split(",") if m]
            self._send(200, {"models": [{"name": m, "model": m, "digest": hashlib.sha256(m.encode()).hexdigest()} for m in models]})
        elif self.path in ("/v1/models", "/models"):
            self._send(200, {"data": [{"id": "local-model"}]})
        else:
            self._send(404, {"error": "not found"})

    def _inference_gate(self) -> bool:
        with _lock:
            _calls["inference"] += 1
            n = _calls["inference"]
        delay = float(os.environ.get("FAKE_DELAY_SECONDS", "0") or 0)
        if delay:
            time.sleep(delay)
        if n <= int(os.environ.get("FAKE_FAIL_FIRST_N", "0") or 0):
            self._send(503, {"error": "model loading"})
            return False
        return True

    def _completion(self, prompt: str) -> str:
        fixed = os.environ.get("FAKE_RESPONSE_TEXT")
        return fixed if fixed is not None else _scripted_findings(prompt)

    def do_POST(self):
        body = self._body()
        if os.environ.get("FAKE_RECORD_FILE"):  # capture wire payloads for byte-level comparisons
            with _lock, open(os.environ["FAKE_RECORD_FILE"], "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"path": self.path, "body": body}, sort_keys=True) + "\n")
        if self.path == "/api/pull":
            self._send(200, {"status": "success"})
        elif self.path == "/api/generate":
            if self._inference_gate():
                prompt = (body.get("system") or "") + "\n" + body.get("prompt", "")
                self._send(
                    200,
                    {
                        "model": body.get("model"),
                        "response": self._completion(prompt),
                        "done": True,
                        "prompt_eval_count": len(prompt) // 4,
                        "eval_count": 32,
                    },
                )
        elif self.path == "/api/chat":
            if self._inference_gate():
                prompt = "\n".join(m.get("content", "") for m in body.get("messages", []))
                self._send(
                    200, {"model": body.get("model"), "done": True, "message": {"role": "assistant", "content": self._completion(prompt)}}
                )
        elif self.path == "/v1/chat/completions":
            if self._inference_gate():
                prompt = "\n".join(m.get("content", "") for m in body.get("messages", []))
                self._send(
                    200,
                    {
                        "model": body.get("model"),
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": self._completion(prompt)}}],
                        "usage": {"prompt_tokens": len(prompt) // 4, "completion_tokens": 32},
                    },
                )
        else:
            self._send(404, {"error": "not found"})


def serve(port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1" if os.environ.get("FAKE_LOCAL_ONLY") else "0.0.0.0", port), Handler)


if __name__ == "__main__":
    srv = serve(int(os.environ.get("FAKE_PORT", "11434")))
    print(f"fake-runtime listening on {srv.server_address}", flush=True)
    srv.serve_forever()
