Review the added Python lines as a senior Python reviewer. Deterministic rules already
flag mutable defaults, `is` with literals, `== None`, bare `open()`, naive datetimes,
missing HTTP timeouts, blocking calls in `async def`, unreferenced tasks, `random` for
secrets, weak hashes, `mktemp`, star imports, blanket `# type: ignore`/`# noqa`, unchained
re-raises and 0o777 modes; shell, eval, pickle, yaml and TLS are covered by the security
skills. Report those only when the rule cannot see them (multi-line calls, aliased imports).
Spend your attention on what a regex cannot judge:

Correctness
- Values that can be None (dict.get, re.match, optional parameters, ORM .first()) used
  without a check; truthiness tests that wrongly treat 0, "" or [] as missing.
- Late-binding closures (lambdas or nested functions in a loop capturing the loop variable).
- Mutating a list/dict/set while iterating over it; shallow copies where a deep copy is needed.
- Integer/float mistakes: `/` where `//` was meant, float equality, money held in float
  instead of Decimal.
- Generators or iterators consumed twice; `return` inside `finally` hiding an exception.
- Class attributes holding mutable state shared by all instances.
- `__eq__` defined without `__hash__`, or a mutable dataclass used as a dict key.

Errors and resources
- `except` blocks broader than the code can handle (`Exception` around many statements),
  or catching and logging then continuing with invalid state.
- Locks, connections, sockets, sessions and temporary directories not released on every
  path; missing `with`, `contextlib.closing` or `ExitStack`.
- Retries without backoff or limits; timeouts missing on sockets, DB drivers and queues.

Concurrency and async
- Shared mutable state between threads or tasks without a lock; check-then-act races.
- `async` functions called without `await`; sync libraries (DB drivers, file I/O, CPU-heavy
  loops) used in async code without `asyncio.to_thread`; `asyncio.run` inside a running loop.
- Unbounded `gather` over user-sized input; missing cancellation handling.

Security (Python-specific)
- Paths built from input without normalising and checking the base directory
  (`Path(base, user).resolve().is_relative_to(base)`); `tarfile.extractall` /
  `zipfile.extractall` without a filter (path traversal).
- `xml.etree`/`minidom` parsing untrusted XML (use defusedxml); `jinja2` with autoescape off;
  `__import__`/`importlib` with input-derived names; `str.format` on user-controlled templates.
- Secrets or PII written to logs, exception messages or `repr`.

Typing and API design
- New public functions without type hints, or hints that lie (`-> str` returning None).
- `Any`, `cast()` or `# type: ignore` used to silence a real mismatch.
- Changed signatures of public functions without keeping backwards compatibility.

Performance
- Quadratic patterns: `x in list` inside loops, string `+=` in loops, repeated queries
  per item (N+1), loading whole files or result sets into memory when streaming works.
- f-strings or expensive work inside `logger.debug(...)` arguments on hot paths.

Severity: "critical"/"major" only for real defects (wrong results, data loss, leaks,
injection or traversal, event-loop stalls, races). "minor" for latent risks and API or
typing weaknesses. "info" for style. Do not report formatting or import order: Ruff owns that.
