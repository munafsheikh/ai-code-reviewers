"""Record the observable behaviour of a legacy single-file review gate.

Runs the legacy gate (path given as argv[1], e.g. Firefly's
tools/review-gate/ReviewGate.java) against the fake runtime for each case in
legacy_cases.json and writes legacy_gate_golden.json. The golden file is the
regression contract the extracted engine's `--format legacy` mode must meet.

  python tests/regression/characterize_legacy.py /path/to/ReviewGate.java
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent))
from tests.support import fake_runtime  # noqa: E402


def run_case(gate: Path, case: dict, port: int) -> dict:
    env = dict(os.environ)
    env["LLM_HOST"] = case.get("host", f"http://127.0.0.1:{port}")
    env["LLM_MODEL"] = case.get("model", "test-model")
    env.pop("JAVA_TOOL_OPTIONS", None)
    if case.get("response") is not None:
        os.environ["FAKE_RESPONSE_TEXT"] = case["response"]
    else:
        os.environ.pop("FAKE_RESPONSE_TEXT", None)
    proc = subprocess.run(["java", str(gate)], input=case.get("diff", "x\n"), text=True, capture_output=True, env=env, timeout=120)
    return {"name": case["name"], "exit_code": proc.returncode, "stdout": proc.stdout.strip()}


def main() -> int:
    gate = Path(sys.argv[1]).resolve()
    cases = json.loads((HERE / "legacy_cases.json").read_text())
    os.environ["FAKE_LOCAL_ONLY"] = "1"
    srv = fake_runtime.serve(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    results = [run_case(gate, c, port) for c in cases]
    srv.shutdown()
    (HERE / "legacy_gate_golden.json").write_text(json.dumps(results, indent=2) + "\n")
    for r in results:
        print(f"{r['name']:<28} exit={r['exit_code']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
