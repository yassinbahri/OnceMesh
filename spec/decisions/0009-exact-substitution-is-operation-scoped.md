# Decision 0009: Exact substitution is operation-scoped

Status: accepted

## Context

The RFC PDF shadow workload produced ten exact parser matches and no mismatches.
The PDF action commits to the full source digest, pypdf version, extraction
profile, limits, and output schema. Repeating the parser is therefore expensive
verification of an already identified deterministic computation.

The same reasoning does not apply to network fetches, whose source can change
without changing the requested URL action.

## Decision

Add an explicit `exact-substitute` policy mode. Permit it only through a runtime
entry point for reviewed deterministic, side-effect-free operations. Initially,
the only supported operation is `document.pdf-to-text/1`.

Exact substitution still requires a fresh trusted result, an allowed tier, and
artifact integrity verification. Any missing authority or failed check executes
the operation normally. The existing live kill switch applies on every call.

## Consequences

PDF parsing can avoid repeated CPU work when identical bytes and parser identity
are seen again. HTTP fetching cannot use this mode, and adding another operation
requires both an adapter contract and an explicit runtime allowlist change.
