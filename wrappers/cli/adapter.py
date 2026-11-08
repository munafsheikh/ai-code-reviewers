"""Subprocess adapter (acr.wrapper/v1).

Executes an operator-configured argv (no shell). The prompt is written to stdin;
stdout is the completion. ``{model}`` in argv is substituted with the model ref.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time

from orchestrator.contracts import AdapterError, Completion, GenerationRequest, Health, ModelAdapter


class CliAdapter(ModelAdapter):
    @property
    def endpoint(self) -> str:
        return "cli:" + " ".join(self._argv("model")[:1])

    def _argv(self, model: str) -> list[str]:
        cmd = self.config.get("command") or os.environ.get("ACR_CLI_COMMAND", "").split()
        return [str(a).replace("{model}", model) for a in cmd]

    def health(self) -> Health:
        argv = self._argv("model")
        if not argv:
            return Health(False, "no command configured (runtime.command or ACR_CLI_COMMAND)")
        if shutil.which(argv[0]) is None:
            return Health(False, f"executable not found: {argv[0]}")
        return Health(True, "ok", [])

    def generate(self, req: GenerationRequest) -> Completion:
        argv = self._argv(req.model)
        if not argv:
            raise AdapterError("no command configured")
        prompt = (req.system + "\n\n" if req.system else "") + req.prompt
        t0 = time.monotonic()
        try:
            proc = subprocess.run(argv, input=prompt, capture_output=True, text=True, timeout=req.timeout_s, shell=False, check=False)
        except subprocess.TimeoutExpired as e:
            raise AdapterError(f"command timed out after {req.timeout_s}s", transient=True) from e
        except OSError as e:
            raise AdapterError(f"cannot execute {argv[0]}: {e}") from e
        if proc.returncode != 0:
            raise AdapterError(f"command exited {proc.returncode}: {proc.stderr[:300]}", transient=False)
        return Completion(text=proc.stdout, model=req.model, latency_ms=int((time.monotonic() - t0) * 1000))
