"""Minimal acr.wrapper/v1 implementation."""

from __future__ import annotations

from orchestrator.contracts import Completion, GenerationRequest, Health, ModelAdapter


class EchoAdapter(ModelAdapter):
    @property
    def endpoint(self) -> str:
        return "echo:"

    def health(self) -> Health:
        return Health(True, "ok", [{"name": "echo", "model": "echo", "digest": "0" * 64}])

    def generate(self, req: GenerationRequest) -> Completion:
        return Completion(text='{"findings": []}', model=req.model, latency_ms=0)
