# Decision 0012: Conformance requires an independent runtime

Status: accepted

## Context

Repeating digest assertions through a second wrapper around the Python reference
does not demonstrate protocol portability. Canonical JSON has language-specific
hazards including number precision, Unicode surrogate handling, key ordering,
and default escaping. Signature verification can also differ by key encoding.

## Decision

Maintain a zero-dependency Node.js conformance runner that reads normative vector
files directly and uses only Node built-ins. It must reproduce positive values,
reject invalid canonical inputs, independently reconstruct receipt signing bytes,
verify Ed25519, and reject tampering.

The Python suite may launch the Node runner, but the Node implementation must
never invoke or import Python reference code.

## Consequences

Changes to canonicalization, action identity, validation records, or receipt
signatures must satisfy two independent runtimes. Node remains a conformance
implementation rather than a full OnceMesh client or store.
