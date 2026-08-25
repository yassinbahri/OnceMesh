# ADR 0003: Prove organization-level reuse before federation

- Status: accepted
- Date: 2026-08-24

## Context

Federation adds discovery, availability, abuse, privacy, deletion, and trust
problems. None improves the correctness of the core action model.

## Decision

v0 defines storage-neutral objects and ordered cache tiers, but does not define
peer discovery or public propagation. The initial validation target is reuse
within one organization.

## Consequences

Stores can later exchange the same manifests and blobs. No DHT, incentive, or
reputation mechanism is part of v0.
