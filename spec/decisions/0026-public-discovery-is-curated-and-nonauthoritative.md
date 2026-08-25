# ADR 0026: Public discovery is curated and non-authoritative

## Decision

The first public-discovery mechanism is a versioned static directory reviewed in
the OnceMesh repository. Discovery metadata and aggregate statistics are
informational. They never modify trust or cause automatic network access to a
listed peer.

## Rationale

A curated document is inspectable, reproducible, inexpensive to host, and easy
to validate in CI. It lets the project learn which metadata and statistics are
useful before introducing an always-on service or decentralized abuse surface.

Separating discovery from trust prevents directory compromise, operator
misrepresentation, ranking manipulation, or stale health data from becoming an
authorization decision.

## Consequences

- Operators submit entries through reviewable repository changes.
- Clients fetch only the canonical HTTPS snapshot or search an explicitly
  selected local snapshot.
- `observed` means endpoint connectivity only.
- Automatic configuration, popularity ranking, DHT discovery, and live probes
  remain out of scope for v0.
