"""Ollama adapter (acr.wrapper/v1)."""

from __future__ import annotations

import time

from orchestrator.contracts import AdapterError, Completion, GenerationRequest, Health, ModelAdapter
from orchestrator.engine.http import request_json


class OllamaAdapter(ModelAdapter):
    def health(self) -> Health:
        try:
            tags = request_json("GET", f"{self.endpoint}/api/tags", timeout=5)
        except AdapterError as e:
            return Health(False, str(e))
        models = tags.get("models", []) if isinstance(tags, dict) else []
        return Health(True, "ok", models)

    def pull(self, model_ref: str, timeout: float = 1800) -> None:
        request_json("POST", f"{self.endpoint}/api/pull", {"name": model_ref, "stream": False}, timeout=timeout)

    def generate(self, req: GenerationRequest) -> Completion:
        t0 = time.monotonic()
        if req.raw:
            # Legacy wire format: exactly what ReviewGate.java sent.
            payload = {"model": req.model, "prompt": req.prompt, "stream": False}
        else:
            options = {
                k: v
                for k, v in {
                    "temperature": req.temperature,
                    "seed": req.seed,
                    "num_predict": req.max_tokens,
                    "num_ctx": req.num_ctx,
                }.items()
                if v is not None
            }
            payload = {"model": req.model, "prompt": req.prompt, "stream": False, "options": options}
            if req.system:
                payload["system"] = req.system
            if req.json_mode:
                payload["format"] = "json"
        body = request_json("POST", f"{self.endpoint}/api/generate", payload, timeout=req.timeout_s)
        if not isinstance(body, dict) or "response" not in body:
            raise AdapterError(f"unexpected response shape from Ollama: {str(body)[:200]}")
        return Completion(
            text=body["response"],
            model=req.model,
            latency_ms=int((time.monotonic() - t0) * 1000),
            prompt_tokens=body.get("prompt_eval_count"),
            completion_tokens=body.get("eval_count"),
        )
