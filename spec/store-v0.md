# OnceMesh local store profile v0

Status: draft

A local store combines an action cache with a content-addressable store (CAS).

## Required behavior

- Blob and manifest writes are atomic from a reader's perspective.
- Blobs are addressed only by validated SHA-256 digests.
- Blob bytes are verified against their descriptor during admissibility.
- Result manifests are immutable.
- Multiple manifests may exist for one action digest.
- Candidate order is newest `produced_at` first.
- A malformed stored manifest produces an explainable store rejection rather
  than an application crash or cache hit.

The filesystem layout is implementation-specific and not an interchange
contract. Implementations must prevent digest strings from becoming arbitrary
filesystem paths.
