# OnceMesh Operation Policy v0

Status: draft
Version identifier: `oncemesh.policy/v0`

## 1. Purpose

The operation policy is the authorization boundary between reusable candidates
and application-visible substitution. A cache hit or successful source check
does not itself grant permission to substitute.

## 2. Policy object

```json
{
  "spec_version": "oncemesh.policy/v0",
  "enabled": true,
  "operations": {
    "http.fetch/1": {
      "mode": "conditional-substitute",
      "trusted_result_producers": ["evaluation:local"],
      "trusted_validation_producers": ["runtime:local"],
      "allowed_tiers": ["organization"],
      "max_validation_ttl_seconds": 3600,
      "receipt_requirement": "optional",
      "trusted_receipt_keys": [],
      "authorization_partition": "public",
      "max_stale_seconds": 0
    }
  }
}
```

Supported modes are:

- `disabled` — execute normally without attempting substitution;
- `shadow` — evaluate a candidate but always execute normally;
- `conditional-substitute` — for `http.fetch/1` only, substitute after a
  successful guarded conditional 304;
- `exact-substitute` — for reviewed, deterministic, side-effect-free operations,
  return a fresh trusted result for the exact action digest without executing the
  operation again;
- `stale-while-revalidate` — for `http.fetch/1` only, return an eligible boundedly
  stale result after background refresh work is scheduled or coalesced.

Unknown operations behave as `disabled`.

`receipt_requirement` is either `optional` or `required`. `optional` preserves
local v0 behavior and does not use receipts as an admissibility gate. `required`
requires a valid receipt whose key is listed in `trusted_receipt_keys` and is
active and producer-authorized in the receipt key registry. An empty trusted-key
list is invalid when receipts are required. In v0, `required` is valid only with
`exact-substitute`; other modes fail policy validation rather than silently
ignoring the gate.

`authorization_partition` is either `public` or `required` and follows
`authorization-partition-v1.md`. Public mode forbids a partition token; required
mode demands an exact caller/action token match before substitution.
In v0, required partitions are supported only by `exact-substitute`; other modes
fail policy validation instead of ignoring the boundary.

`max_stale_seconds` is zero for modes other than `stale-while-revalidate`. SWR
requires a positive value and follows `stale-while-revalidate-v1.md`.

## 3. Reload and failure behavior

The reference file registry re-reads and validates the policy for every
operation. A missing, malformed, unreadable, unsupported, or internally
inconsistent policy **MUST** fail closed to ordinary execution. It must never
fall back to substitution.

Policy failure is recorded as an audit reason without exposing file contents.

## 4. Emergency controls

Substitution is disabled when either:

- top-level `enabled` is false; or
- environment variable `ONCEMESH_DISABLE_SUBSTITUTION` is one of `1`, `true`,
  `yes`, or `on`, compared case-insensitively.

The environment switch is evaluated for every operation. It cannot enable
substitution; it can only disable it.

## 5. Conditional HTTP substitution

Substitution is permitted only when:

1. The exact operation policy is `conditional-substitute`.
2. The candidate result producer is trusted.
3. The candidate comes from an allowed tier.
4. Candidate artifact digests and sizes verify.
5. The result metadata carries an ETag or Last-Modified validator.
6. The guarded transport returns HTTP 304 for those exact validators.
7. The local validation producer is trusted.
8. The new freshness interval does not exceed `max_validation_ttl_seconds`.

If any condition fails, OnceMesh performs the full GET and returns its output.
A 200 conditional response is the full result and may be published normally.

## 6. Audit result

Every invocation records whether substitution occurred and a non-sensitive
decision reason. Required reasons include `conditional_304`, `policy_disabled`,
`kill_switch`, `policy_error`, `candidate_missing`, `tier_denied`,
`validator_missing`, `validator_untrusted`, and `source_changed`.

## 6.1 Exact deterministic substitution

An `exact-substitute` decision is permitted only when:

1. The operation is explicitly listed with that mode.
2. Its action identity commits to every input byte, executor name and version,
   configuration value, and output schema.
3. The operation is deterministic and side-effect-free by its adapter contract.
4. The result is fresh, its producer is trusted, and its tier is allowed.
5. Every artifact digest and size verifies before return.
6. When receipts are required, a policy-trusted active key verifies a receipt
   bound to the exact result manifest and producer.

The reference runtime supports this mode for `document.pdf-to-text/1`. It must
fail closed to execution for an absent candidate, denied tier, policy error,
kill switch, or incompatible policy mode. A successful reuse is recorded as
`exact_fresh_hit`.

Receipt enforcement failure reasons include `receipt_registry_missing`,
`receipt_registry_error`, `receipt_missing`, `receipt_key_untrusted`,
`receipt_key_unknown`, `receipt_key_revoked`, `receipt_producer_denied`, and
`receipt_invalid`. Every such failure executes the operation normally.

## 7. Non-goals

This policy does not authorize unconditional URL-cache hits, side-effect
suppression, public federation, or semantic substitution.

The reference `substitute` evaluation consumes an existing evaluation corpus,
an already-warmed store, and an explicit policy file. Its report passes only
when every invocation substitutes after a 304 and no rollback control activates.
