# Running a real organization pilot

Use a workload whose deterministic computation is expensive enough to benefit
from exact reuse. `document.pdf-to-text/1` is the current proven candidate; HTTP
fetch remains disabled for automatic substitution.

## Before starting

1. Copy `evaluation/organization-pilot/pilot.json.template` outside the source
   tree and replace every placeholder.
2. Use a pseudonymous organization ID and role IDs; do not record employee names,
   tenant identifiers, source URLs, payloads, credentials, or keys.
3. Obtain workload, security, and operations approval.
4. Configure managed TLS, receipt-key custody, retention, monitoring, rollback,
   and incident ownership.
5. Run in shadow mode before allowing narrowly scoped substitution.

## Daily evidence

Create one daily record per configured operation and UTC date from operational
metrics. The `evidence_digest` binds the underlying write-once internal evidence
retained by the operator; that internal evidence is not copied into this public
repository.

Generate the report without overwriting prior evidence:

```bash
oncemesh-pilot report \
  --config /secure/pilot.json \
  --record /secure/daily-2026-09-01.json \
  --record /secure/daily-2026-09-02.json \
  --output /secure/pilot-report.json
```

The command exits with status 2 unless every threshold passes and
`environment_kind` is `real`. Synthetic fixtures can test calculations but
cannot become externally reviewable evidence.

## Federation sign-off

Closing the federation milestone additionally requires a second organization
with a distinct administrative ID, signing key, managed TLS endpoint, and
operator. Run the existing origin and receiver preflight and acceptance sequence,
then have each organization retain and sign its own report digest. One operator
must never generate or possess both organizations' private seeds.
