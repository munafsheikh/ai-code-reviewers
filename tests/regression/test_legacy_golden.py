"""The `legacy` profile reproduces Firefly ReviewGate.java exactly (stdout + exit code).

The golden file was recorded by running the original Java gate against the fake
runtime (tests/regression/characterize_legacy.py). Re-record only when the legacy
contract intentionally changes.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from orchestrator import config as cfg
from orchestrator.engine import prompt

HERE = Path(__file__).parent
GOLDEN = {g["name"]: g for g in json.loads((HERE / "legacy_gate_golden.json").read_text())}
CASES = json.loads((HERE / "legacy_cases.json").read_text())
# sha256 of the SYSTEM_PROMPT text block in Firefly's ReviewGate.java at extraction time.
LEGACY_PROMPT_SHA256 = "03e58eab78ef736ab6c4a28eab828667f8f21adc95cdaf9e3c9e9e9b58855090"


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_matches_reviewgate(case, runtime, monkeypatch):
    if case.get("response") is not None:
        monkeypatch.setenv("FAKE_RESPONSE_TEXT", case["response"])
    env = {k: v for k, v in os.environ.items() if not k.startswith("ACR_MODEL_HOST")}
    env["LLM_HOST"] = case.get("host", runtime)
    env["LLM_MODEL"] = case.get("model", "test-model")
    proc = subprocess.run(
        [sys.executable, "-m", "orchestrator", "review", "--profile", "legacy", "--format", "legacy"],
        input=case.get("diff", "x\n"),
        text=True,
        capture_output=True,
        env=env,
        timeout=60,
        cwd=cfg.home(),
    )
    golden = GOLDEN[case["name"]]
    assert proc.returncode == golden["exit_code"], proc.stderr
    assert proc.stdout.strip() == golden["stdout"]


def test_legacy_prompt_is_byte_identical():
    skill = cfg.load_skills()["lang.java.first-pass-gate"]
    assert hashlib.sha256(skill.prompt.encode()).hexdigest() == LEGACY_PROMPT_SHA256


def test_legacy_truncation_matches_reviewgate():
    skill = cfg.load_skills()["lang.java.first-pass-gate"]
    p = prompt.build_legacy(skill, "x" * 30_000)
    assert p.endswith("x" * 10 + "\n...[diff truncated for review]...\n```\n")
    assert p.count("x") - skill.prompt.count("x") == 24_000


@pytest.mark.skipif(not os.environ.get("LEGACY_REVIEWGATE"), reason="set LEGACY_REVIEWGATE=/path/to/ReviewGate.java")
def test_wire_payload_identical_to_original(tmp_path, monkeypatch, runtime):
    """Byte-level check against the original Java gate (needs a JDK and the source file)."""
    rec = tmp_path / "rec.jsonl"
    monkeypatch.setenv("FAKE_RECORD_FILE", str(rec))
    monkeypatch.setenv("FAKE_RESPONSE_TEXT", "SEVERITY: NONE")
    diff = (cfg.home() / "benchmarks/fixtures/java-leak-injection/diff.patch").read_text()
    env = {k: v for k, v in os.environ.items() if k != "JAVA_TOOL_OPTIONS"} | {"LLM_HOST": runtime, "LLM_MODEL": "m"}
    subprocess.run(["java", os.environ["LEGACY_REVIEWGATE"]], input=diff, text=True, env=env, check=True, capture_output=True)
    subprocess.run(
        [sys.executable, "-m", "orchestrator", "review", "--profile", "legacy", "--format", "legacy"],
        input=diff,
        text=True,
        env=env,
        check=True,
        capture_output=True,
        cwd=cfg.home(),
    )
    java, ours = (json.loads(line) for line in rec.read_text().splitlines())
    assert java == ours
