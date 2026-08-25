# Decision 0015: Federation starts public, explicit, and non-transitive

Status: accepted

## Context

Peer-to-peer exchange expands the confidentiality, licensing, trust, and abuse
surface more than local or organization caching. Automatic discovery and private
artifact exchange would combine too many unvalidated assumptions in the first
experiment.

## Decision

Require explicit local peer configuration and affirmative per-result `public`
classification. Authenticate availability snapshots and production receipts with
separately configured Ed25519 keys. Permit only exact allowlisted operations and
bounded transfers into a dedicated leased cache. Bound availability snapshot age
and future clock skew so a signed pre-withdrawal snapshot cannot be replayed
indefinitely.

Imported results are never re-exported by the reference catalog. Withdrawal stops
new distribution but does not claim remote deletion; receiving retention policy
governs already transferred bytes.

## Consequences

The experiment can demonstrate digest-preserving exchange between independently
configured organizations without weakening either side's policy. It does not yet
solve private federation, network discovery, durable replication, distributed
rate limiting, or legal classification automation.
