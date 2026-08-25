# Readiness assessment

## Current decision

OnceMesh `0.1.0` is accepted as an alpha code-release candidate and as a tool for
a controlled, monitored pilot. It is not accepted as proven production
infrastructure for unattended or multi-organization deployment.

“Ready” is split into three gates so a local simulation cannot silently stand in
for operational proof.

| Gate | Status | Meaning |
| --- | --- | --- |
| Code release | Accepted | Local and hosted tests, static checks, schemas, packages, dependency audit, CodeQL, and Docker rehearsal pass. |
| Controlled organization pilot | Prepared | Strict tooling and runbook exist. A real workload, accountable owners, measurement window, and rollback drills are still required. |
| Public reference operator | Prepared locally | A bounded single-origin specification and hardened Compose profile exist. Public DNS, managed TLS, key custody, an independent receiver, and a seven-day canary are still required. |
| Independent federation production | Blocked | Requires separately administered operators, infrastructure, key custody, governance, and signed evidence. One-host Docker cannot satisfy it. |

## Locally verified controls

- Exact identity and canonicalization have portable Python and Node conformance.
- Trust, authorization partition, freshness, receipt, replay, request-bound, and
  public-only federation failure paths are tested.
- Mutable adapters share one identity/storage/index implementation and include
  crash, reopen, migration, contention, and stale-value non-resurrection tests.
- Release artifacts are scanned for caches, evaluation output, signing seeds,
  and private-key material, then installed in a clean environment.
- Runtime dependencies are audited against the current vulnerability database.
- The complete unit/conformance suite currently measures 77% branch-aware source
  coverage; CI rejects regressions below 75% and prints every missed branch.
- Synthetic organization evidence exits unsuccessfully and Docker evidence is
  permanently labeled non-independent.
- The final public commit passed the 11-job Ubuntu/Windows hosted CI matrix in
  113 seconds of wall time and CodeQL with zero open alerts after review. See
  [`hosted-release-validation-0.1.0-20260825.json`](../evaluation/results/hosted-release-validation-0.1.0-20260825.json).

## Operator obligations

A deployment owner must still provide managed TLS and secrets, least-privilege
filesystem and service access, backups and retention, monitoring and alerting,
dependency updates, incident response, workload-specific capacity tests, and a
tested kill switch. The local SQLite and filesystem implementations do not add
distributed consensus, remote backup, or service-level guarantees.

The first-party deployment profile is in
[`deploy/public-operator`](../deploy/public-operator/). Its loopback default,
single-replica constraint, external evidence gates, and rollback requirements
are defined by
[`public-reference-operator-v0`](../spec/public-reference-operator-v0.md).

## Promotion rule

Do not describe OnceMesh as production-proven until both external gates have
reviewable evidence. A successful local test, hosted CI run, synthetic pilot, or
signature-valid result is necessary evidence for its own scope but cannot prove
semantic correctness, economic benefit, independent administration, or
production reliability.
