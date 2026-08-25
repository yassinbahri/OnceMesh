# OnceMesh Authenticated Federation HTTP Transport v0

Status: experimental
Request version: `oncemesh.federation-request/v0`
Bundle version: `oncemesh.federation-bundle/v0`

## 1. Purpose

This transport carries the public-only federation experiment between explicitly
configured peers. It adds receiver authentication, request replay resistance,
timeouts, bounded responses, and strict endpoint behavior. It does not change
result admissibility: the receiver still verifies availability, result,
production receipt, artifact integrity, and its own local policy.

## 2. Endpoints

An origin exposes exactly two GET endpoint forms:

- `/v0/availability`
- `/v0/bundles/sha256:<64 lowercase hexadecimal characters>`

Requests have no body. Redirects are not followed. Successful responses use
`application/json`; all other content types fail closed. Unknown methods and
paths do not expose catalog data.

## 3. Authenticated request

Every request carries these headers:

- `OnceMesh-Peer-ID`: configured receiving peer identity;
- `OnceMesh-Timestamp`: UTC RFC 3339 timestamp ending in `Z`;
- `OnceMesh-Nonce`: 32 lowercase hexadecimal characters generated randomly per
  request;
- `OnceMesh-Key-ID`: SHA-256 digest of the raw Ed25519 public key;
- `OnceMesh-Signature`: unpadded base64url Ed25519 signature.

The signed request object is:

```json
{
  "spec_version": "oncemesh.federation-request/v0",
  "peer_id": "org-b",
  "timestamp": "2026-08-24T22:00:00Z",
  "nonce": "00112233445566778899aabbccddeeff",
  "method": "GET",
  "path": "/v0/availability",
  "body_digest": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
}
```

The signature input is the ASCII domain separator
`OnceMesh federation HTTP request v1\x00` followed by canonical JSON for the
request object. The key identifier is transported separately and is not part of
the signed object because it is derived from the configured public key.

The server verifies exact peer identity, key identifier, signature, method,
path, empty-body digest, maximum request age, and future clock skew. It accepts a
nonce at most once inside the authentication window. Replay storage is bounded;
when it cannot safely remember another nonce, authentication fails closed.

## 4. Responses

Availability responses contain the signed `oncemesh.availability/v0` object
unchanged.

A bundle response is:

```json
{
  "spec_version": "oncemesh.federation-bundle/v0",
  "manifest": {},
  "receipt": {},
  "artifacts": {
    "result": "<unpadded base64url bytes>"
  }
}
```

Artifact keys are the exact manifest artifact names. Values are canonical
unpadded base64url. The receiver rejects unknown fields, invalid encodings,
duplicate JSON keys, response bytes beyond its transport limit, and decoded
artifact bytes beyond federation policy. The existing bundle verifier remains
authoritative for digest and size integrity.

## 5. Transport policy

Clients require HTTPS by default. Plain HTTP is permitted only by an explicit
option intended for loopback testing. Connect/read duration and raw response
bytes are locally bounded. TLS authenticates the network endpoint and protects
metadata; signed requests authenticate the configured receiving peer; signed
availability and production receipts authenticate protocol claims.

The reference pilot server provides bounded concurrent request handling and a
per-peer sliding-window request limit. An Internet deployment still requires
managed TLS certificates, a hardened reverse proxy, observability, durable or
shared replay and rate-limit state, and denial-of-service controls before JSON
parsing.

## 6. Failure behavior

Authentication failures return a generic unauthorized response without naming
the failed check. Missing bundles return not found. Clients translate transport,
status, content-type, size, and decoding failures into a federation miss. No
partially decoded bundle is published.

## 7. Non-goals

- peer discovery or trust-on-first-use;
- private artifact transfer;
- remote execution;
- redirects, compression, batching, or recursive fetches;
- semantic equivalence;
- production-grade Internet serving.
