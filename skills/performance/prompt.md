Find performance defects introduced by the added lines:
- queries or remote calls inside loops (N+1), missing pagination, unbounded result sets
- blocking I/O on async/event-loop threads, synchronous calls in hot paths
- accidentally quadratic algorithms, repeated expensive work that could be cached
- unbounded caches, collections or queues (memory growth)
Report only issues with a concrete cost; do not suggest micro-optimisations.
