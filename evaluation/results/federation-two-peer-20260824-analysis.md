# Trusted federation experiment analysis — 2026-08-24

Two independently configured reference peers exchanged one explicitly public
result. The receiving peer reproduced the origin action, result, and artifact
digests exactly, admitted the origin producer and receipt key under its own
policy, and stored the bundle in a separate leased cache.

Negative tests reject non-public publication, untrusted peer and receipt keys,
disallowed operations and producers, oversized catalogs and transfers, tampered
availability and artifact bytes, stale replayed snapshots, and snapshots beyond
the allowed future clock skew. Withdrawal removes the result from subsequent
signed catalogs and stops bundle fetches. A previously imported copy remains
only through the receiver's local lease and is removed on expiry. Imported
results cannot be fed directly into the export catalog, preventing transitive
trust in the reference implementation.

The availability signature format has a portable vector reproduced by Python
and an independent zero-dependency Node.js verifier. Availability keys and
production-receipt keys are separate trust decisions.

This completes the M3 reference implementation, not the real-organization exit
criterion. The experiment uses an in-process transport. A deployment between
separately operated organizations still needs network authentication, bounded
parsing, rate limits, quotas, timeouts, operational key custody, and a public
artifact classification review.
