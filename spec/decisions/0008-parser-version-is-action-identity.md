# ADR 0008: Parser version and extraction profile are action identity

- Status: accepted
- Date: 2026-08-24

## Context

PDF text extraction can change across parser releases and configuration even
when source bytes do not change.

## Decision

The exact parser version, extraction profile, page limit, and output limit are
included in the PDF action. Only exact matches are reusable.

## Consequences

Parser upgrades intentionally cause cache misses. Cross-version reuse would
require a separately specified compatibility claim and is absent from v1.
