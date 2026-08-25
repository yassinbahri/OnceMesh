# ADR 0002: Exact action matching in v0

- Status: accepted
- Date: 2026-08-24

## Context

Semantic similarity can find potentially reusable work, but it does not prove
that substituting the result preserves program behavior.

## Decision

The v0 protocol supports exact action-digest matching only. Semantic discovery,
if added later, may return candidates but may not itself authorize reuse.

## Consequences

v0 sacrifices some hit rate for predictable behavior. Adapters must normalize
operation-specific inputs before constructing an action.
