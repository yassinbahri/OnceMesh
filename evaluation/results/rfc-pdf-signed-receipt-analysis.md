# Signed receipt enforcement analysis — 2026-08-24

The RFC PDF exact-substitution policy was changed from optional receipts to
required receipts. Forty existing evaluation result manifests were backfilled
with immutable receipts signed by the deliberately public RFC 8032 conformance
seed. The evaluation registry contains only the corresponding public key.

The signed corpus run completed 20/20 exact substitutions. Every selected result
passed producer trust, freshness, allowed-tier, artifact-integrity, policy key,
active registry state, Ed25519 signature, result-digest binding, and producer
binding checks. Lookup plus verification took 0.58 seconds total and no parser
execution occurred.

A separate live RFC 9309 operation used the same valid result and receipt while
the registry marked its key revoked. Substitution immediately stopped, the parser
executed normally in 0.31 seconds, and the audit reason was
`receipt_key_revoked`. The intentionally failing promotion checks in that report
are the expected proof of fail-closed behavior.

The published conformance private seed is evaluation-only and provides no
production identity assurance. Production deployment still requires protected
private-key storage, organization-controlled public keys, rotation procedures,
and revocation ownership.
