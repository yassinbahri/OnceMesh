# OnceMesh Simulated M3 Acceptance Environment v0

Status: draft
Evidence label: `simulated`

## 1. Purpose

The environment rehearses the complete M3 acceptance sequence inside isolated
containers controlled by one host operator. It validates technical separation,
network behavior, secret scoping, withdrawal, retention, and evidence collection
before involving an external organization.

It must never be represented as evidence of independent organizational control.
The host operator can inspect the container runtime, images, networks, and all
mounted data. Every report therefore records `environment_kind: simulated` and
`administrative_independence: false`.

## 2. Roles and isolation

The harness creates three roles:

- `org-a-origin`: owns the availability and production-receipt seeds, TLS key,
  reviewed public publication, and origin manifest;
- `org-b-receiver`: owns the request seed, receiver policy, exact action,
  durable leased cache, and receiver evidence;
- `untrusted-peer`: owns a distinct request seed but has no entry in the origin's
  authorized requester configuration.

Each role runs as a non-root user with a read-only root filesystem, a private
temporary directory, and only its own read-only secret mount. The origin and
receiver share no secret or writable volume. A private bridge network provides
name resolution; the origin exposes no host port during the automated run.

## 3. Test certificate boundary

The harness creates an ephemeral private test CA and an origin certificate for
the container DNS name. The receiver trusts only that CA for the run. The CA and
all identities are test-only and are destroyed with the sandbox workspace.

This verifies TLS path and hostname handling but is not managed-certificate
evidence.

## 4. Required sequence

1. Both configured roles pass offline preflight.
2. The receiver imports the exact public result over verified TLS.
3. Action, advertised result, imported result, and artifact digests match.
4. The untrusted peer is denied and receives no catalog entries.
5. The origin produces a new write-once manifest with the target publication
   withdrawn and restarts from that manifest.
6. A new receiver run reports `not_available` while its prior durable cache entry
   still exists inside its unexpired lease.
7. After real lease expiry, pruning removes the entry, receipt, and unreferenced
   artifact bytes. A time override may be used only when the report explicitly
   labels the check simulated.
8. The harness scans manifests, public reports, and service logs for every test
   seed and authentication header name. No match is permitted.

## 5. Evidence

The orchestrator emits `oncemesh.federation-simulated-acceptance-report/v0` with:

- image and scenario identifiers;
- role isolation assertions;
- TLS, success, denial, withdrawal, and pruning results;
- exact public digests and byte counts;
- secret-scan result;
- `environment_kind: simulated`;
- `administrative_independence: false`;
- limitations preventing use as the real M3 exit artifact.

## 6. Pass condition

The simulated gate passes only when every technical scenario passes and all
secret scans are clean. Passing means the implementation and operator workflow
are ready for external execution. It does not change the M3 roadmap status.
