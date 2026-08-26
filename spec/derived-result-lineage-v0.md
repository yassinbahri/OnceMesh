# OnceMesh derived-result lineage v0

Status: draft

## 1. Purpose

This profile propagates admissibility through exact multi-hop computations. It
does not make mutable sources content-addressed and does not infer dependencies.

## 2. Result manifest v1

`oncemesh.result/v1` contains every result v0 member plus:

```json
{
  "dependencies": [
    {
      "name": "source-document",
      "result_digest": "sha256:<upstream-result-manifest-digest>"
    }
  ]
}
```

Dependency names and result digests MUST each be unique within one result.
Dependencies MUST be sorted by name before publication. Each `result_digest`
identifies one exact immutable result manifest, not an action alias or a mutable
cache key.

An empty dependency array is valid, but producers SHOULD continue to publish
result v0 when they are not making a lineage claim.

The producing action MUST still identify every upstream byte and other value
that can affect its output. A dependency link adds provenance and cascading
admissibility; it does not compensate for incomplete action identity.

## 3. Effective admissibility

A result v1 is admissible only when:

1. the result passes the ordinary action, producer, freshness, and artifact
   checks;
2. every dependency digest resolves to an exact manifest in the locally
   configured store set;
3. every dependency recursively passes producer, freshness, invalidation,
   artifact-integrity, and lineage checks under the same policy; and
4. traversal remains within the policy's depth and total-dependency bounds.

This makes the effective freshness boundary the earliest currently admissible
boundary in the dependency graph. A trusted source-validation record for an
unchanged upstream result can extend its freshness. A new upstream result does
not validate an older dependency merely because both share an action digest.

## 4. Invalidation record

An explicit early invalidation is an immutable object:

```json
{
  "spec_version": "oncemesh.invalidation/v0",
  "result_digest": "sha256:<result-manifest-digest>",
  "invalidated_at": "2026-08-26T12:00:00Z",
  "producer": "operator:example",
  "reason": "source.changed"
}
```

The record digest is SHA-256 over Action v0 canonical JSON. A record is
effective only when its producer is trusted for invalidation under local policy
and `invalidated_at` is not later than the evaluation time. Once effective, it
is monotonic: later freshness validation does not restore the invalidated result.
A corrected computation is published as a new immutable result.

Recommended reason identifiers include `source.changed`, `producer.revoked`,
`integrity.invalid`, and `operator.manual`. Reason strings are explanatory and
MUST NOT grant trust or select policy.

## 5. Bounds and cycles

The reference policy defaults to a maximum depth of 8 and at most 64 dependency
edges per lookup. Limits MUST be positive integers. Re-visiting a result digest
on the active traversal path is a cycle and MUST fail closed.

Limit failures, cycles, missing results, unreadable records, and invalid
dependency manifests MUST produce machine-readable rejection reasons.

## 6. Storage and compatibility

Stores persist result manifests by both action digest and exact result digest.
The result-digest index is immutable. Publishing the digest index before the
action index is safe: an interrupted publication can leave an unreachable
immutable object but cannot expose a root hit whose digest is not resolvable.

Result v0 remains admissible under its existing rules and has no dependencies.
Implementations MUST NOT rewrite v0 manifests into v1.

Policies for operations that require cascading admissibility SHOULD set
`require_lineage`. Such a lookup rejects result v0 with `lineage_required`,
preventing fallback to a legacy result after a newer v1 candidate is rejected.

## 7. Federation boundary

Federation v0 does not transport lineage or invalidation records and MUST reject
all result v1 manifests. A future federation profile requires explicit limits,
complete bundles, independent trust evaluation, and non-transitive authorization.
