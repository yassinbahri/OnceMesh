# Evaluation workloads

The cross-process adapter transaction stress profile is run with
`python evaluation/adapter-stress/run.py`. Its extreme profile covers exact
epoch counts, same-key contention, mixed operations, forced process exit,
reopen integrity, and bounded lock recovery.

The SQLite performance tier is evaluated with
`python evaluation/sqlite-index-stress/run.py`. It performs a same-run JSON
baseline, 20,000 SQLite operations, WAL-reader and forced-exit probes, and an
integrity check. Run the same script in Linux to exercise the second platform.

Evaluation manifests are reviewable grants of narrow network authority. Do not
add a URL unless its retrieval and processing are permitted.

`example-smoke.json` exercises the real transport with two passes over the IANA
example domain. It validates wiring and safety controls; it is not statistically
meaningful product evidence.

Use a unique evaluation ID for every run. Reusing an ID intentionally combines
events and will fail the completeness gate when the count exceeds the manifest.
## RFC PDF workload

Run the deterministic PDF extraction shadow workload with `pdf-run`. After a
zero-mismatch report and explicit policy review, `pdf-substitute` exercises the
operation-scoped exact-substitution path using
`policies/rfc-pdf-exact.json`. Source PDFs are still fetched to determine their
exact content digests; only the versioned parser computation is substituted.
