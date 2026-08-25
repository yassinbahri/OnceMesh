# M4 runtime bridge analysis — 2026-08-24

## Outcome

The local real-framework evaluation passed every acceptance check. OnceMesh now
has a framework-neutral execution cache core and a thin LangGraph compatibility
adapter. A deterministic LangGraph node executed once across two exact
invocations in both synchronous and asynchronous graphs.

## Safety evidence

- Exact runtime, ordered namespace, key, serializer, private authorization
  partition, and clear epochs participate in action identity.
- A different authorization partition could not observe the cached value.
- Generic runtime values were rejected when a federation-import store was
  configured.
- A live disable returned misses without deleting the retained entry.
- Namespace clearing rotated identity and made the old entry unreachable.
- Raw tenant identifiers and serialized payloads were absent from result
  manifests.
- Core tests additionally cover TTL expiry, no-expiry private entries, corrupt
  artifacts, producer distrust, envelope validation, global clear, and persisted
  filesystem epochs.

## Regression evidence

- Python 3.12 optional-runtime environment: 140 tests passed, including three
  real LangGraph 1.2.11 tests.
- Independent Node.js conformance implementation: 29 checks passed.
- Docker three-role federation regression: all 20 checks passed, including TLS,
  untrusted-peer denial, withdrawal, real lease expiry, pruning, and secret scan.

## Limits

LangGraph is the first implemented framework adapter, not the core abstraction.
Additional runtime adapters still need their own compatibility tests. The
evaluation is local and uses an in-memory result store; filesystem epoch
persistence is unit-tested. Multi-process epoch coordination and performance
benchmarking remain future work. Generic framework values intentionally remain
outside public federation.
