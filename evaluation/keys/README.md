# Evaluation receipt keys

`rfc-pdf-conformance-key.json` contains the public key derived from the published
RFC 8032 seed used by OnceMesh's portable conformance vector. It is intentionally
public and must never be trusted for production or organization-private data.

The live RFC workload uses it only to exercise receipt enforcement reproducibly.
Real deployments must generate and protect their own private keys, distribute
only public keys here, and maintain an operational rotation and revocation plan.
