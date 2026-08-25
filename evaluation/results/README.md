# Evaluation evidence index

This directory contains committed, content-free measurements and analyses. JSON
is the machine-readable evidence; matching Markdown explains method, limits, and
interpretation. Evidence is historical and must not be read as a guarantee for a
different workload or deployment.

## Release summary

The [`0.1.0` release-candidate report](release-candidate-0.1.0-20260825.json)
records the final package, test, adapter, Node, schema, and Docker checks. Its
[analysis](release-candidate-0.1.0-20260825-analysis.md) explicitly separates
local acceptance from external proof.

The broader [repository-readiness report](repository-readiness-0.1.0-20260825.json)
and [analysis](repository-readiness-0.1.0-20260825-analysis.md) cover source
control hygiene, coverage, governance, dependency security, and the defect found
during the final audit.

The [hosted release-validation report](hosted-release-validation-0.1.0-20260825.json)
and [analysis](hosted-release-validation-0.1.0-20260825-analysis.md) record the
successful public Ubuntu/Windows CI matrix, job durations, CodeQL result, and
security-finding disposition for the final hardened commit.

## Significant measurements

| Area | Recorded result | Evidence |
| --- | --- | --- |
| Cross-language protocol | 29 independent Node checks passed | [`cross-language-conformance-node-20260824.json`](cross-language-conformance-node-20260824.json) |
| Open adapter platform | 9 checks passed with real LangGraph, LangChain, and LlamaIndex packages | [`adapter-platform-20260824.json`](adapter-platform-20260824.json) |
| Cross-process durability | 11,600 operations on Windows and 11,600 in non-root Linux preserved committed state | [`adapter-stress-20260824.json`](adapter-stress-20260824.json), [`adapter-stress-linux-20260824.json`](adapter-stress-linux-20260824.json) |
| SQLite/WAL tier | 20,000 operations per platform; 3.756× Windows and 6.109× Linux speedup over the JSON baseline | [`sqlite-index-stress-20260824.json`](sqlite-index-stress-20260824.json), [`sqlite-index-stress-linux-20260824.json`](sqlite-index-stress-linux-20260824.json) |
| Federation rehearsal | 20 isolation, trust, TLS, withdrawal, lease, and secret checks passed after the repository audit | [`federation-simulated-acceptance-20260825-repository-regression.json`](federation-simulated-acceptance-20260825-repository-regression.json) |
| Exact parser reuse | 183.02 s net avoidable parser time in shadow; 10/10 eligible parser executions avoided in controlled substitution | [`rfc-pdf-10-20260824.json`](rfc-pdf-10-20260824.json), [`rfc-pdf-10-substitution-20260824.json`](rfc-pdf-10-substitution-20260824.json) |
| Hosted release gate | 11 CI jobs passed in 113 s wall time; CodeQL completed with zero open alerts after review | [`hosted-release-validation-0.1.0-20260825.json`](hosted-release-validation-0.1.0-20260825.json) |

## Evidence classes

- `example-*`, `python-docs-*`, and `rfc-pdf-*` are controlled workload
  evaluations, not organization-wide economics.
- `federation-http-*`, `federation-two-peer-*`, and `federation-tls-*` are local
  transport evidence.
- `federation-simulated-*` is deliberately non-independent, regardless of pass
  status.
- A real organization pilot will be stored outside package distributions and
  must follow `spec/organization-pilot-v0.md`.

Raw payloads, tenant identifiers, credentials, and private keys must never be
committed as evidence.
