# ADR 0020: Agent-runtime integration uses a framework-neutral bridge

Status: accepted

## Context

Agent frameworks expose similar cache boundaries with different native key,
batch, TTL, async, and serialization conventions. Implementing OnceMesh policy
inside each framework adapter would create divergent identity and trust rules.
Generic framework values can also contain private state and serializer-specific
types that are unsuitable for public federation.

## Decision

OnceMesh defines one execution cache bridge over exact runtime, namespace, key,
serializer, and private authorization partition fields. Framework adapters only
translate their native contract to typed bytes and core bridge calls.

The v0 bridge is local or organization scoped and never federates generic
framework values. LangGraph is the first adapter and compatibility proof, not a
special case in the core protocol.

## Consequences

Identity, freshness, clearing, trust, and disable behavior remain consistent as
new runtime adapters are added. Cross-operator reuse will require later,
operation-specific portable output profiles instead of exposing arbitrary
framework cache state.
