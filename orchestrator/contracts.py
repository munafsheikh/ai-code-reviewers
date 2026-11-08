"""Versioned data contracts shared by the engine, wrappers and skills.

Interface ids:
  acr.result/v1   review result document (see schemas/review-result.schema.json)
  acr.wrapper/v1  model adapter contract (ModelAdapter below)
  acr.skill/v1    skill manifest (see schemas/skill.schema.json)
  acr.model/v1    model manifest (see schemas/model.schema.json)
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any

RESULT_SCHEMA = "acr.result/v1"
SEVERITIES = ("info", "minor", "major", "critical")
CONFIDENCES = ("low", "medium", "high")
KINDS = ("verified", "hypothesis")
SOURCES = ("rule", "model")


def severity_rank(sev: str) -> int:
    return SEVERITIES.index(sev)


def confidence_rank(conf: str) -> int:
    return CONFIDENCES.index(conf)


@dataclass
class Location:
    path: str
    start_line: int
    end_line: int | None = None
    verified: bool = True  # False when a model cited a line outside the changed hunks


@dataclass
class Finding:
    rule_id: str
    skill: str
    title: str
    severity: str
    category: str
    location: Location
    explanation: str
    evidence: str
    remediation: str
    confidence: str
    kind: str
    source: str
    model: str | None = None
    corroborated_by: list[str] = field(default_factory=list)
    suppressed: dict[str, Any] | None = None

    @property
    def fingerprint(self) -> str:
        # Line numbers are excluded so the fingerprint survives unrelated edits above.
        norm = " ".join(self.evidence.split())
        raw = f"{self.rule_id}|{self.location.path}|{norm}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["fingerprint"] = self.fingerprint
        return d


@dataclass
class GenerationRequest:
    model: str
    prompt: str
    system: str | None = None
    temperature: float | None = 0.0
    seed: int | None = 42
    max_tokens: int | None = 1024
    num_ctx: int | None = None
    timeout_s: float = 120.0
    json_mode: bool = False
    raw: bool = False  # send prompt only, no options (legacy wire format)


@dataclass
class Completion:
    text: str
    model: str
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached: bool = False


@dataclass
class Health:
    ok: bool
    detail: str
    models: list[dict[str, Any]] = field(default_factory=list)


class AdapterError(Exception):
    """Raised by wrappers. ``transient`` errors are eligible for bounded retry."""

    def __init__(self, message: str, transient: bool = False):
        super().__init__(message)
        self.transient = transient


class ModelAdapter:
    """Base class for acr.wrapper/v1 adapters. Subclasses live in wrappers/<id>/."""

    interface = "acr.wrapper/v1"

    def __init__(self, config: dict[str, Any]):
        self.config = config

    @property
    def endpoint(self) -> str:
        return str(self.config.get("base_url", ""))

    def health(self) -> Health:  # pragma: no cover - abstract
        raise NotImplementedError

    def generate(self, request: GenerationRequest) -> Completion:  # pragma: no cover - abstract
        raise NotImplementedError

    def model_digest(self, model_ref: str) -> str | None:
        for m in self.health().models:
            if m.get("name") == model_ref or m.get("model") == model_ref:
                return m.get("digest")
        return None
