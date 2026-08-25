# ADR 0021: Runtime adapters share codecs, not policy

Status: accepted

## Context

Runtime frameworks differ in key shape, batching, TTL, async behavior, and value
serialization. They should not differ in OnceMesh identity, trust, freshness,
partitioning, or rollback decisions.

## Decision

Introduce a small runtime adapter SDK over the framework-neutral execution-cache
bridge. Codecs convert runtime values to typed bytes. Adapters translate native
calls and keys. The bridge remains the only policy and storage authority.

The SDK validates that a codec's stable identifier matches the serializer bound
into action identity. It provides common sync and async lookup, publication, and
lookup-or-execute behavior. Exceptions are not cached.

## Consequences

LangGraph and native Python exercise the same cache logic, and later framework
adapters require less security-sensitive code. Mutable framework contracts such
as enumeration and per-key deletion require an explicit index profile rather
than accidental changes to the immutable core.
