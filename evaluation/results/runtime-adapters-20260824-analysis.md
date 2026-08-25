# M5 runtime adapter SDK analysis — 2026-08-24

## Outcome

M5 passed. Native Python and LangGraph now use the same runtime adapter SDK over
the framework-neutral execution-cache bridge. The SDK owns typed codec binding,
sync and async lookup/publication, and lookup-or-execute behavior; neither
integration reimplements core cache policy.

The repeatable evaluation passed 6/6 checks. Native Python synchronous and
asynchronous operations each executed once across two exact calls. A cached null
was correctly distinguished from a miss. Operation failure produced no cache
manifest, serializer mismatch failed during construction, and a real LangGraph
graph continued to reuse its node result through the shared SDK.

## Additional test evidence

Eight SDK-focused tests also cover failed encoding, malformed type-tag fallback,
TTL expiry, namespace clear, live disable, falsey values, and authorization
partition isolation. JSON encoding rejects unsupported objects, non-string map
keys, non-finite numbers, and Unicode surrogate code points.

## Regression evidence

- Python 3.12 with LangGraph 1.2.11: 148 tests passed.
- Python 3.14 without the optional dependency: 148 tests passed with the three
  LangGraph-only tests skipped as designed.
- Independent Node.js conformance: 29 checks passed.
- Docker federation rehearsal: all 20 checks passed; the adapter work did not
  weaken TLS, peer trust, withdrawal, lease, pruning, or secret controls.

## Limits and next boundary

The native Python facade requires callers to supply exact keys deliberately; it
does not infer identity from arbitrary objects. LlamaIndex ingestion is a
promising next adapter, but its current cache contract includes key enumeration
and per-key deletion. Supporting it durably requires a specified mutable
active-key index layered over immutable OnceMesh objects. Multi-process clear
coordination and performance benchmarks also remain follow-on work.
