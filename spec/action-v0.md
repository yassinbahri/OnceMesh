# OnceMesh Action Protocol v0

Status: draft
Version identifier: `oncemesh.action/v0`

## 1. Purpose

This specification defines how to identify a computation, describe its output,
and decide whether an existing output is admissible as a substitute for running
that computation again.

The protocol does not determine that an arbitrary computation is cacheable.
Applications and adapters are responsible for admitting only read-only or
otherwise replay-safe operations.

## 2. Model

OnceMesh separates four concepts:

1. **Action** — every declared value that can affect a computation's output.
2. **Artifact** — immutable output bytes addressed by their digest.
3. **Result manifest** — a mapping from one action digest to its artifacts.
4. **Receipt** — a producer's claim about how a result was produced.

An action cache maps an action digest to one or more candidate result manifests.
A content-addressable store (CAS) maps artifact digests to bytes.

## 3. Digest and canonicalization

All v0 digests use SHA-256 and have the textual form `sha256:<lowercase-hex>`.

An action digest is:

```text
"sha256:" + hex(SHA-256(canonical_json(action)))
```

The v0 canonical JSON profile is UTF-8 JSON with:

- object keys sorted by Unicode code point;
- no insignificant whitespace;
- quotation mark and reverse solidus escaped as `\"` and `\\`;
- U+0008, U+0009, U+000A, U+000C, and U+000D escaped as `\b`, `\t`, `\n`,
  `\f`, and `\r`; other U+0000 through U+001F characters escaped using
  lowercase `\u00xx`; all other Unicode scalar values encoded directly;
- only objects, arrays, strings, integers, booleans, and null;
- integers restricted to `[-(2^53)+1, (2^53)-1]`;
- duplicate object keys forbidden;
- Unicode surrogate code points forbidden;
- floating-point numbers forbidden.

Adapters **MUST** convert domain decimals and floating-point values to a stable
string representation and document that representation. The restricted profile
avoids cross-runtime number serialization differences in v0.

Artifact digests are computed over the exact artifact bytes, without JSON
canonicalization or media-type metadata.

## 4. Action

An action has these required members:

```json
{
  "spec_version": "oncemesh.action/v0",
  "operation": {"name": "document.parse", "version": "1"},
  "inputs": {},
  "executor": {"name": "parser", "version": "2.1.0", "config": {}},
  "output_schema": "example.org/markdown-v1",
  "vary": {}
}
```

- `operation.name` identifies operation semantics, not a Python function name.
- `operation.version` changes when those semantics change.
- `inputs` contains inline values or descriptors for content-addressed inputs.
- `executor` identifies the implementation and output-affecting configuration.
- `output_schema` identifies the expected interpretation of result artifacts.
- `vary` declares hidden output-affecting context without including secrets.

Common `vary` keys include tenant partition, authorization-scope digest, locale,
region, feature-set digest, and model deployment revision. A secret **MUST NOT**
appear directly. An adapter may include a non-reversible partition identifier.

Time, randomness, mutable remote state, undeclared environment variables, and
identity are inputs when they can affect output. If they cannot be represented
reliably, the operation **MUST NOT** be shared through OnceMesh.

`scope`, TTL, producer, signatures, and storage location are deliberately not
part of the action. They affect admissibility or distribution, not computation.

## 5. Artifact descriptor

An artifact descriptor contains:

```json
{
  "name": "document",
  "digest": "sha256:<hex>",
  "size": 123,
  "media_type": "text/markdown"
}
```

The CAS **MUST** verify the digest when accepting or retrieving bytes. `name`
must be unique within one result manifest.

## 6. Result manifest

```json
{
  "spec_version": "oncemesh.result/v0",
  "action_digest": "sha256:<hex>",
  "artifacts": [],
  "produced_at": "2026-08-24T12:00:00Z",
  "fresh_until": "2026-08-25T12:00:00Z",
  "producer": "local:developer"
}
```

`fresh_until` may be null only when the operation specification defines a
content-derived validity rule. Timestamps use UTC RFC 3339 with `Z`.

The manifest digest uses the same canonical JSON and SHA-256 procedure as an
action. A result manifest is immutable; refreshing creates another manifest.

Result manifest v1 and its exact dependency lineage are defined by
[`derived-result-lineage-v0.md`](derived-result-lineage-v0.md). Content identity
proves which upstream bytes were used; it does not by itself prove that a
mutable upstream source remains fresh.

## 7. Receipt

A receipt binds a result manifest digest to production metadata:

```json
{
  "spec_version": "oncemesh.receipt/v0",
  "result_digest": "sha256:<hex>",
  "producer": "https://cache.example.com/identity/team-a",
  "executor_environment": {"platform": "linux/amd64"},
  "signature": null
}
```

Unsigned receipts retain `signature: null`. The optional Ed25519 signature
envelope is defined by `receipt-signature-v1.md`; identity discovery remains
deployment-defined.
Implementations **MUST NOT** interpret a valid signature as proof that output is
correct. It proves only that the associated identity signed the receipt.

## 8. Lookup and admissibility

Stores are searched in policy order, normally:

```text
run -> local/project -> organization -> trusted federation
```

Federation transport is not defined in v0.

A candidate is admissible only when all configured checks pass:

1. Its `action_digest` exactly equals the requested action digest.
2. Every artifact exists and its bytes match its descriptor digest and size.
3. The result is fresh under the caller's policy.
4. The producer and receipt satisfy the caller's trust policy.
5. The caller is authorized to read every artifact.
6. The operation-specific policy accepts the result.

Failure of any check is a cache miss, not a partially trusted hit. An
implementation **SHOULD** return machine-readable rejection reasons.

## 9. Publication

Publication is opt-in. The producer chooses a distribution scope independently
of the action digest. Implementations **MUST** default to local-only publication.
Moving an identical manifest to a wider scope does not change its digest.

Before publishing beyond the local scope, an implementation must have an
affirmative policy covering confidentiality, authorization, source terms, and
artifact licensing.

## 10. Side effects

v0 results may substitute only computations declared replay-safe. OnceMesh must
not suppress required writes, payments, messages, audit events, rate-limit
accounting, or other externally observable effects.

## 11. Required observability

Implementations **SHOULD** record:

- hit or miss;
- tier selected;
- candidate rejection reason;
- action digest and operation name;
- estimated time and cost saved;
- artifact bytes transferred;
- freshness age.

Logs must not expose secrets or raw private inputs.

## 12. Non-goals for v0

- probabilistic or semantic cache substitution;
- consensus about artifact correctness;
- automatic or authoritative public peer discovery (the optional informational
  directory is defined by `public-mesh-directory-v0` and never grants trust);
- remote execution;
- mutation or invalidation of immutable artifacts;
- prescribing a specific database, CAS, or wire transport.
