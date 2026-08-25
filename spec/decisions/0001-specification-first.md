# ADR 0001: Specification-first development

- Status: accepted
- Date: 2026-08-24

## Context

OnceMesh aims to let independent implementations decide whether a computation
result can replace execution. Behavior inferred from one SDK would make
cross-language compatibility and safety auditing difficult.

## Decision

Normative behavior is written before implementation. Each observable protocol
rule must have a portable conformance example where practical. The Python code
is a reference implementation, not the protocol definition.

## Consequences

Protocol changes require a specification and vector change. Implementation-only
features may be experimental but cannot be described as interoperable.
