"""`python -m orchestrator.schema_check FILE...` — validate review result documents (CI helper)."""

import json
import sys

from orchestrator import schema


def main(paths: list[str]) -> int:
    rc = 0
    for p in paths:
        errs = schema.validate(json.load(open(p, encoding="utf-8")), schema.load("review-result"))
        print(f"{p}: {'valid' if not errs else 'INVALID'}")
        for e in errs[:20]:
            print(f"  {e}")
        rc |= bool(errs)
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
