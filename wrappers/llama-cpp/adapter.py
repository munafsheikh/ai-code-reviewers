"""llama.cpp / OpenAI-compatible chat completions adapter (acr.wrapper/v1)."""

from __future__ import annotations

import os
import time

from orchestrator.contracts import AdapterError, Completion, GenerationRequest, Health, ModelAdapter
from orchestrator.engine.http import request_json


class LlamaCppAdapter(ModelAdapter):
    def _headers(self) -> dict[str, str]:
        key = os.environ.get(self.config.get("api_key_env", "ACR_LLAMA_API_KEY"), "")
        return {"Authorization": f"Bearer {key}"} if key else {}

    def health(self) -> Health:
        try:
            body = request_json("GET", f"{self.endpoint}/v1/models", timeout=5, headers=self._headers())
        except AdapterError as e:
            return Health(False, str(e))
        models = [{"name": m.get("id"), "model": m.get("id")} for m in (body or {}).get("data", [])]
        return Health(True, "ok", models)

    def generate(self, req: GenerationRequest) -> Completion:
        t0 = time.monotonic()
        messages = ([{"role": "system", "content": req.system}] if req.system else []) + [{"role": "user", "content": req.prompt}]
        payload = {"model": req.model, "messages": messages, "stream": False}
        if not req.raw:
            payload.update(
                {k: v for k, v in {"temperature": req.temperature, "seed": req.seed, "max_tokens": req.max_tokens}.items() if v is not None}
            )
            if req.json_mode:
                payload["response_format"] = {"type": "json_object"}
        body = request_json("POST", f"{self.endpoint}/v1/chat/completions", payload, timeout=req.timeout_s, headers=self._headers())
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise AdapterError(f"unexpected response shape: {str(body)[:200]}") from e
        usage = body.get("usage") or {}
        return Completion(
            text=text,
            model=req.model,
            latency_ms=int((time.monotonic() - t0) * 1000),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )
