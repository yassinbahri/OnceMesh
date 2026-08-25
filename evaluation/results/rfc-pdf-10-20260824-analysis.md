# RFC PDF exact-substitution analysis — 2026-08-24

## Outcome

The two-pass shadow workload completed 40 operations: 20 HTTP fetches and 20
`document.pdf-to-text/1` executions. All 20 second-pass candidates matched their
executed outputs byte-for-byte. There were no mismatches or rejected candidates.

The parser stage accounted for 327.76 seconds of execution across both passes.
On the verified second pass, parser reuse would have saved 183.02 seconds after
lookup overhead. Ten parser candidates contained 5.52 MB of reusable text and
metadata.

The subsequent policy-controlled run performed 20/20 exact substitutions. It
returned 11.05 MB of verified artifacts, invoked no parser work, and spent 0.49
seconds in content-store lookup across all twenty operations. The overall command
still fetched source PDFs so their exact byte digests could identify the parser
actions; fetch freshness remains governed separately.

## Decision

Promote `document.pdf-to-text/1` to narrowly scoped `exact-substitute` eligibility.
Keep `http.fetch/1` on its separate conditional-validation policy. Do not extend
exact substitution to URLs, nondeterministic operations, OCR, encrypted PDFs, or
unversioned parser configurations.

The live environment kill switch, per-operation policy reload, trusted producer,
freshness, allowed-tier, and artifact-integrity checks remain mandatory. Adding
another exact-substitution operation requires a new adapter contract, shadow
corpus, zero-mismatch evidence, and an explicit runtime allowlist change.
