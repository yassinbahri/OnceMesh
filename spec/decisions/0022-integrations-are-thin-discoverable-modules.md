# ADR 0022: Integrations are thin, discoverable modules

Status: accepted

## Context

An open-source integration ecosystem becomes difficult to maintain when each
adapter owns storage, serialization, policy, clearing, and framework glue. It
also makes optional dependencies leak into core imports and encourages subtle
security differences.

## Decision

Canonical adapter code lives in `oncemesh.integrations`. Shared exact behavior,
codecs, mutable indexing, and metadata are separate modules. Framework adapters
translate their native interface and delegate everything else.

The built-in registry is dependency-free. Optional framework imports are lazy
at the module boundary. Legacy v0 imports remain behavior-free shims.

## Consequences

Contributors have one template and a small review surface. Applications can
install only the adapters they use or install the aggregate `adapters` extra.
Mutable framework semantics are explicit and cannot weaken immutable core or
federation boundaries.
