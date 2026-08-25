# ADR 0004: Shadow evaluation before result substitution

- Status: accepted
- Date: 2026-08-24

## Context

An incorrect cache hit can silently change application behavior. Hit rate alone
does not show whether an action identity captures every output-affecting input.

## Decision

New operation profiles begin in shadow mode. OnceMesh performs lookup but always
executes the operation, compares exact artifacts, and records verified potential
savings. Substitution is a later, per-operation policy decision.

## Consequences

Initial deployments save no compute. They produce direct evidence about hit
quality, mismatch causes, and expected economics before assuming substitution
risk.
