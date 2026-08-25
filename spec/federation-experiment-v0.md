# OnceMesh Trusted Federation Experiment v0

Status: experimental
Availability version: `oncemesh.availability/v0`
Schema: `schemas/availability-v0.schema.json`

## 1. Purpose

The experiment permits two explicitly configured organizations to exchange an
artifact that its origin has affirmatively classified as public. It tests trust,
identity, integrity, limits, withdrawal, and retention without introducing peer
discovery, semantic matching, or transitive federation.

## 2. Explicit peer configuration

A receiving organization configures each peer out of band with:

- exact `peer_id`;
- raw Ed25519 availability public key;
- trusted result-receipt key identifiers and public keys;
- trusted result producers;
- allowed operation name/version pairs;
- maximum availability entries, artifact bytes, and total transfer bytes;
- maximum availability age and tolerated future clock skew;
- local retention duration.

An unconfigured peer is unreachable by design. Peer configuration is local
policy and is never accepted from the peer itself.

## 3. Public publication catalog

Federation export is opt-in per immutable result manifest. The origin supplies
the exact action, result manifest, production receipt, and classification.
Only classification `public` is accepted. Private, internal, confidential,
unknown, or missing classifications are rejected before catalog insertion.

Catalog insertion verifies action/result binding, artifact availability and
integrity, receipt/result binding, and receipt structure. It does not broaden the
origin store's general publication defaults.

## 4. Signed availability manifest

```json
{
  "spec_version": "oncemesh.availability/v0",
  "peer_id": "org-a",
  "generated_at": "2026-08-24T12:00:00Z",
  "entries": [
    {
      "action_digest": "sha256:<hex>",
      "result_digest": "sha256:<hex>",
      "operation": {"name": "document.pdf-to-text", "version": "1"},
      "artifact_bytes": 1234
    }
  ],
  "signature": {
    "profile": "oncemesh.ed25519/v1",
    "key_id": "sha256:<raw availability public-key digest>",
    "value": "<unpadded base64url Ed25519 signature>"
  }
}
```

Entries are sorted by action digest then result digest. The signature input is
the ASCII domain separator `OnceMesh availability manifest v1\x00` followed by
canonical JSON for the complete manifest with `signature` replaced by null.

Availability signing keys authenticate a peer catalog snapshot. Production
receipt keys authenticate result claims. The receiver configures both trust
dimensions independently.

A receiver rejects a signed snapshot older than its configured maximum age or
dated beyond its configured future clock skew. This bounds replay of a snapshot
captured before withdrawal. Availability timestamps are not result-freshness
claims; result freshness remains part of the immutable result manifest.

## 5. Import

For an exact requested action, the receiver:

1. validates the availability structure, entry limit, configured peer identity,
   availability key identifier, signature, maximum age, and future clock skew;
2. selects only an entry whose action digest and operation exactly match;
3. rejects operations outside the peer allowlist;
4. fetches the exact result bundle by result digest;
5. verifies result digest, action binding, trusted producer, production receipt
   signature and manifest binding, every artifact digest and size, and all byte
   limits;
6. imports the immutable result into a dedicated federation cache with a local
   retention lease.

Any failure is a miss with a non-sensitive reason. Partial bundles are never
published to the receiving cache.

## 6. Limits and abuse behavior

The receiver enforces limits before and during transfer. A manifest with too many
entries, an advertised oversized result, an actual oversized artifact, or total
bytes beyond policy fails closed. v0 has no compression, recursive dependencies,
batch expansion, or peer-provided redirects.

The reference experiment is an in-process transport and does not claim network
rate limiting or denial-of-service resistance. Network deployments additionally
need authentication, timeouts, quotas, request-rate limits, and bounded parsing.

## 7. Withdrawal and retention

The origin may withdraw a result digest from its catalog. Withdrawal removes it
from the next signed availability manifest and prevents new bundle fetches. It
does not mutate the immutable origin result.

Federation cannot promise deletion of bytes already transferred to another
organization. The receiver assigns a local retention lease at import. After the
lease expires, the dedicated federation cache removes the result reference and
unreferenced artifact and receipt bytes. A receiver may prune earlier under local
policy. Re-import requires the result to be currently advertised again.

## 8. Non-goals

- automatic or public peer discovery;
- transitive trust or forwarding imported results;
- private artifact federation;
- distributed consensus about correctness;
- semantic or approximate matching;
- remote deletion guarantees;
- a production network transport.
