"""The model-matrix planner must work without git (it runs in a slim Python container)."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("model_matrix", ROOT / "infrastructure/scripts/model_matrix.py")
mm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mm)


def test_changed_selection_uses_file_list_and_disk_budget(tmp_path, capsys, monkeypatch):
    changed = tmp_path / "changed.txt"
    changed.write_text("models/registry/qwen2.5-coder-0.5b.toml\nmodels/registry/qwen3-coder-30b-a3b.toml\nREADME.md\n")
    monkeypatch.setenv("PATH", "")  # no git available
    assert mm.plan(["--select", "changed", "--changed-files", str(changed), "--max-disk-mb", "6000"]) == 0
    out = capsys.readouterr()
    assert [r["id"] for r in json.loads(out.out)] == ["qwen2.5-coder-0.5b"]
    assert "qwen3-coder-30b-a3b" in out.err  # skipped, and says why


def test_small_selection_and_report(tmp_path, capsys):
    assert mm.plan(["--select", "small"]) == 0
    ids = {r["id"] for r in json.loads(capsys.readouterr().out)}
    assert "qwen2.5-coder-1.5b" in ids and "qwen3-coder-30b-a3b" not in ids
    run = tmp_path / "qwen2.5-coder-0.5b"
    run.mkdir()
    (run / "result.json").write_text(
        json.dumps(
            {
                "id": "qwen2.5-coder-0.5b",
                "ref": "qwen2.5-coder:0.5b",
                "pulled": True,
                "digest": "abc",
                "bench": {"metrics": {"precision": 0.9}, "cases": []},
            }
        )
    )
    assert mm.report(str(tmp_path)) == 0
    assert "| `qwen2.5-coder-0.5b` |" in capsys.readouterr().out
