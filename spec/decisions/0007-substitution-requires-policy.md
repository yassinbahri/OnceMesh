# ADR 0007: Substitution requires a reloadable fail-closed policy

- Status: accepted
- Date: 2026-08-24

## Context

Protocol validity and cache integrity do not express an operator's current risk
tolerance. Rollback must not require rebuilding or restarting an application.

## Decision

Application-visible substitution requires an explicit per-operation policy.
The reference registry reloads on each call, treats all policy errors as
disabled, and checks an environment kill switch. v0 enables only conditional
HTTP substitution after an authoritative 304 response.

## Consequences

Operators can disable reuse immediately. Policy parsing adds small per-call
overhead. A policy outage reduces savings but does not prevent the underlying
operation from executing.
