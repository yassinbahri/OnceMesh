# ADR 0006: Freshness extensions are attached immutable records

- Status: accepted
- Date: 2026-08-24

## Context

Changing `fresh_until` on an existing result would change immutable metadata or
misrepresent revalidation as fresh execution. Replacing `produced_at` would
erase when the artifact bytes were actually observed.

## Decision

Later source checks create immutable validation records attached to the exact
result-manifest digest. Admissibility may use trusted records to extend
freshness, while the original manifest and artifacts remain unchanged.

## Consequences

Stores need a validation-record index. Trust applies separately to the result
producer and validator. Deleting a validation record cannot corrupt the result;
it only removes that freshness evidence.
