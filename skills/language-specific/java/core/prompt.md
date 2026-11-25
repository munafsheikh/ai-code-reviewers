Review the added Java lines for: null-safety, resource leaks (unclosed
streams/connections), SQL injection risk, hardcoded secrets/credentials,
obvious concurrency bugs, and swallowed exceptions. Use "critical"/"major"
only for actual bugs (leaks, injection, hardcoded secrets, swallowed exceptions
that hide errors); "minor" for style/nits.

Deterministic rules already flag: Throwable/Error catches, lost interrupts, lock()
outside try/finally, static SimpleDateFormat, double/float money, BigDecimal from
double, java.util.Random for secrets, MD5/SHA-1/DES/ECB, discarded exception causes,
@Transactional on private/final methods, field injection, concatenated log messages
and newCachedThreadPool. Report those only where a rule cannot see them (split across
lines, aliased types). Also look for:

- Null-safety: unchecked returns of Map.get, Optional misuse (as a field or
  parameter, isPresent()+get()), auto-unboxing of a nullable Integer/Long/Boolean,
  Integer/Long compared with == outside the -128..127 cache.
- Money and time: BigDecimal compared with equals() (scale-sensitive) instead of
  compareTo, divide() without scale and RoundingMode, missing currency, LocalDateTime
  where an Instant or ZonedDateTime is needed, System.currentTimeMillis for durations
  (use nanoTime / Clock).
- Concurrency: check-then-act on shared maps (use computeIfAbsent/merge), non-volatile
  double-checked locking, HashMap/ArrayList/SimpleDateFormat shared between threads,
  CompletableFuture without an executor or exception handling, blocking or
  synchronized code pinning virtual threads.
- Equality and collections: equals() without hashCode(), mutable objects used as map
  keys, modifying a collection while iterating, returning internal mutable collections.
- Spring and JPA: self-invocation bypassing @Transactional/@Async/@Cacheable proxies,
  N+1 queries from lazy associations in loops, EAGER fetch on collections, entities
  returned from controllers, missing @Valid on request bodies, checked exceptions
  that do not roll back a transaction.
- Security: XML parsers (DocumentBuilderFactory, SAXParserFactory, XMLInputFactory)
  without XXE protections, path traversal from request input, open redirects,
  Runtime/ProcessBuilder with input, PII or secrets in logs and exception messages.
- API design: public signature changes without compatibility, nullable returns
  where Optional or an empty collection is expected.
