Assess design issues introduced by the added lines:
- layering violations (e.g. UI or controller code issuing raw SQL), circular dependencies
- breaking changes to public APIs, schemas or wire formats without versioning
- responsibilities mixed in one unit, hidden global state, configuration hardcoded in code
- missing error boundaries around I/O and external calls
Severity "major" only for issues that will cause defects or block change; otherwise "minor".
