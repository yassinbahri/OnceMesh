# Federation operator handoff analysis — 2026-08-24

The repository now contains the complete local tooling needed to hand M3 to two
independent operators. Each side can generate its own Ed25519 identity without
printing the seed, exchange a public identity document, and run a network-free
preflight against the exact manifest later used by the pilot command.

The origin publication packager requires both an explicit `public`
classification and a separate review-confirmation flag. Before writing its
canonical, write-once output, it checks the exact action/result binding, the
production receipt key and signature, producer and result binding, artifact name
coverage, and every artifact digest and size. Failed review, tampering, or an
existing output path produces no package.

Preflight reports contain only public identities, configuration limits, endpoint
names, and immutable digests. They omit seeds, artifact bytes, authentication
signatures, and nonces. Operators can exchange these reports and compare the
availability, request, and receipt key identifiers before opening the endpoint.

The included templates are intentionally incomplete and fail validation until
all placeholders are replaced. The runbook covers key creation, secret loading,
publication packaging, offline preflight, service startup, probing, and cleanup.
Native ACL and secret-manager integration remain operator-specific, particularly
on Windows and shared filesystems.

No further local simulation can satisfy M3's organizational independence
requirement. The next evidence must come from the two real administrative
environments using this handoff package.
