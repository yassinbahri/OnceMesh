# Decision 0017: External pilot keeps secrets out of manifests and evidence

Status: accepted

## Context

A convenient all-in-one pilot configuration could place private seeds beside
public trust and policy data. That would make review, version control, and
evidence collection likely secret-exposure paths.

## Decision

Deployment manifests contain public keys, peer identities, paths, endpoints,
and non-secret limits only. They refer to private seeds by environment-variable
name. Evidence records only public identities, digests, sizes, policy bounds,
and outcomes. TLS private keys remain local files handled by the process or its
supervisor and are never copied into evidence.

## Consequences

Operators can review and exchange manifests without exchanging private signing
material. Process environments and TLS-key permissions become deployment
responsibilities and must be audited separately.
