# ADR 0029: Derived freshness is bounded by exact result lineage

- Status: accepted
- Date: 2026-08-26

## Context

Content identity proves which bytes were used. It does not prove that those
bytes still represent a mutable live source. A derived result can therefore be
reproducible from an upstream artifact while no longer being admissible for a
current request.

Result v0 has no machine-readable upstream lineage. Applications can copy an
upstream TTL onto a derived result, but lookup cannot verify that dependency,
honor a later source validation, or propagate an explicit early invalidation.

## Decision

Result manifest v1 adds an ordered, uniquely named `dependencies` array. Each
entry commits to the digest of one exact upstream result manifest. The result
manifest digest and any receipt signature therefore commit to the lineage.

A v1 result is admissible only when every dependency is independently
admissible under the same time and producer-trust policy. This recursively
bounds derived freshness by the result's own freshness and every required
upstream result. Trusted validation records for unchanged upstream bytes can
extend that upstream result's freshness. A changed source produces a new result
digest and does not extend the old dependency.

Immutable invalidation records provide an explicit, trusted, monotonic signal
that a result must stop being admitted before its TTL expires. Invalidation
changes admissibility; it never deletes or mutates the result or its artifacts.

Traversal is local to the configured store set, detects cycles, and is bounded
by policy depth and total-dependency limits. Missing, malformed, unreadable,
untrusted, invalidated, cyclic, or excessive dependency state fails closed.

Result v0 remains readable with its existing behavior. It carries no lineage
claim. Policies can require lineage to prevent fallback to legacy v0 candidates.
Recursive federation bundles remain out of scope.

## Consequences

- Producers must publish result v1 when they want cascading admissibility.
- Adapters must still place output-affecting upstream content in action identity;
  lineage does not repair an incomplete action key.
- Stores need an immutable result-digest index and invalidation-record index.
- Existing v0 objects are not rewritten and cannot silently gain lineage.
- Applications can distinguish reproducibility from current-source
  admissibility without destructive cache invalidation.
