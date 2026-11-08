Review the added Java lines for: null-safety, resource leaks (unclosed
streams/connections), SQL injection risk, hardcoded secrets/credentials,
obvious concurrency bugs, and swallowed exceptions. Use "critical"/"major"
only for actual bugs (leaks, injection, hardcoded secrets, swallowed exceptions
that hide errors); "minor" for style/nits.
