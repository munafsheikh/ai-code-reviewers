"""In-process CLI coverage for every subcommand."""

import json

from orchestrator.cli.main import main
from tests.conftest import FIXTURES


def test_validate_passes(capsys):
    assert main(["validate"]) == 0
    assert "0 errors" in capsys.readouterr().out


def test_skills_and_models_list(capsys):
    assert main(["skills"]) == 0 and main(["models", "list"]) == 0
    out = capsys.readouterr().out
    assert "security.secrets" in out and "qwen2.5-coder-1.5b" in out


def test_models_verify_against_runtime(runtime, capsys):
    assert main(["models", "verify"]) == 0
    assert "unpinned (runtime digest" in capsys.readouterr().out


def test_models_verify_runtime_down(monkeypatch):
    monkeypatch.setenv("ACR_MODEL_HOST", "http://127.0.0.1:9")
    assert main(["models", "verify"]) == 2


def test_health(runtime, capsys):
    assert main(["health"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ok"
    assert main(["health", "--profile", "offline"]) == 0


def test_bench_gate(tmp_path, capsys):
    out = tmp_path / "b.json"
    assert main(["bench", "--gate", "--out", str(out)]) == 0
    assert json.loads(out.read_text())["metrics"]["recall"] == 1.0 and out.with_suffix(".md").exists()


def test_docs_check_is_current(capsys):
    assert main(["docs", "check"]) == 0


def test_evolve_report(tmp_path, capsys):
    p = tmp_path / "proposal.md"
    assert main(["evolve", "--out", str(p)]) == 0
    assert "Improvement proposal" in p.read_text() and "digest unpinned" in p.read_text()


def test_review_exit_codes_and_stdout(capsys):
    assert main(["review", "--profile", "offline", "--diff", str(FIXTURES / "python-clean/diff.patch")]) == 0
    assert "**PASS**" in capsys.readouterr().out
    assert main(["review", "--profile", "offline", "--format", "json", "--diff", str(FIXTURES / "typescript-types/diff.patch")]) == 0
    assert json.loads(capsys.readouterr().out)["gate"]["status"] == "warn"
    assert main(["review", "--profile", "offline", "--diff", "/nonexistent.patch"]) == 2
