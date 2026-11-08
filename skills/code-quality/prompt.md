Find correctness defects introduced by the added lines:
- swallowed or ignored errors, error paths that leave state inconsistent
- null/undefined dereferences, off-by-one errors, unchecked casts, wrong comparisons
- resource leaks (unclosed streams, connections, files, locks)
- obvious concurrency bugs (unsynchronised shared mutable state, check-then-act races)
