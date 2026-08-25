# ADR 0005: Evaluation manifests grant narrow network authority

- Status: accepted
- Date: 2026-08-24

## Context

A benchmark runner that accepts arbitrary URLs can become an SSRF mechanism or
retrieve sources the operator did not intend to process.

## Decision

Evaluation manifests contain both explicit URLs and an exact hostname allowlist.
The reference runner permits HTTPS, validates resolved addresses, revalidates
redirects, bounds requests, and carries no ambient credentials.

## Consequences

Adding a source is a reviewable manifest change. Application checks are backed
by network-boundary controls in production because DNS rebinding cannot be
fully prevented at this layer.
