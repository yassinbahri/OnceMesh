# Decision 0010: Receipt signatures authenticate claims, not correctness

Status: accepted

## Context

Producer names in result manifests are currently local trust-policy labels. A
portable result needs a verifiable binding between the result digest, producer,
and declared executor environment. Cryptographic verification alone cannot show
that the executor was honest, deterministic, authorized, or correctly configured.

## Decision

Define `oncemesh.ed25519/v1` for production receipts. The signature covers a
domain-separated canonical form of the complete unsigned receipt. Key IDs are
SHA-256 digests of raw Ed25519 public keys. Receipt verification also requires
an exact result-manifest digest and producer match.

Keep signature validity separate from admissibility. Callers must still enforce
trusted keys and producers, exact action identity, freshness, allowed tiers,
artifact integrity, authorization, and operation policy.

Signed publication is opt-in in the reference implementation. Existing unsigned
local results remain valid under policies that do not require receipt signatures.
Making signatures mandatory is a later policy-version change that must include
key distribution, rotation, and revocation behavior.

## Consequences

Independent implementations can reproduce and verify the conformance vector.
Receipts can be stored immutably beside results without changing result digests.
Compromise of a signing key authenticates forged claims from that key, so key
management remains an explicit deployment responsibility.
