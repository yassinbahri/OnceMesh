# OnceMesh Authorization Partition v1

Status: draft
Profile identifier: `oncemesh.authorization-partition/v1`

## 1. Purpose

An authorization partition prevents results produced under different tenants,
subjects, or authorization scopes from sharing an action identity. It is a
defense against accidental cross-boundary reuse, not an access token and not a
replacement for store or application authorization.

Private authorization claims must not appear directly in actions, metrics,
manifests, or receipts.

## 2. Partition claims

The local application constructs:

```json
{
  "profile": "oncemesh.authorization-partition/v1",
  "tenant": "<stable local tenant identifier>",
  "scopes": ["<sorted unique scope>"] ,
  "subject_partition": null
}
```

`tenant` is required and non-empty. `scopes` is a non-empty set represented in
Unicode code-point sorted order. `subject_partition` is null unless output or
read authority varies by a stable local subject grouping; when present it is a
non-empty string. Secrets and bearer credentials must never be claims.

## 3. Derivation

The partition key is deployment-local secret key material containing at least 32
bytes. It must be independent of receipt-signing keys.

The derivation input is the ASCII domain separator
`OnceMesh authorization partition v1\x00` followed by the OnceMesh canonical JSON
encoding of the claims object. The token is:

```text
hmac-sha256:<lowercase hex HMAC-SHA-256>
```

The action includes only this token as `vary.authorization_partition`. Different
keys deliberately produce different action identities, preventing organizations
from correlating private partitions through shared tokens.

## 4. Policy enforcement

Each operation policy declares `authorization_partition` as:

- `public`: substitution is allowed only when the action has no
  `vary.authorization_partition` and the caller supplies no partition token;
- `required`: substitution requires a canonical token in the action and an
  exact constant-time match with the caller-supplied token.

Missing, malformed, forbidden, or mismatching partitions fail closed to normal
execution and produce a non-sensitive audit reason. They never fall back to a
candidate from another partition.

## 5. Security boundary

Possession of a partition token does not authorize reading a result. Applications
and remote stores must authenticate callers and enforce artifact access
separately. Tokens reduce accidental cache-key aliasing and metadata exposure;
they do not protect weak claims if the HMAC key is compromised.

Rotating a partition key changes every affected action digest and causes safe
cache misses. Deployments may overlap old and new caches operationally, but one
action contains exactly one partition token.
