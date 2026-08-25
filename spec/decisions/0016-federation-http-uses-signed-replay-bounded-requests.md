# Decision 0016: Federation HTTP uses signed, replay-bounded requests

Status: accepted

## Context

Signed availability authenticates the origin's catalog but does not identify a
receiver requesting it or a result bundle. TLS alone also leaves receiver
identity and replay behavior dependent on deployment-specific infrastructure.

## Decision

Authenticate every federation GET with a domain-separated Ed25519 signature
from an explicitly configured receiver. Bind the signature to peer identity,
timestamp, nonce, exact method and path, and the empty-body digest. Enforce a
bounded time window and single-use nonce at the server. Require bounded response
reads and HTTPS by default; allow plain HTTP only explicitly for loopback tests.

Keep transport authentication separate from availability and production-receipt
trust. All three checks remain necessary and use independently configured keys.

## Consequences

Captured requests cannot be changed or replayed inside a server process, and an
unconfigured receiver cannot enumerate the catalog through the reference
transport. Multi-process deployments need shared replay state. Signed requests
do not replace TLS, rate limiting, or denial-of-service controls.
