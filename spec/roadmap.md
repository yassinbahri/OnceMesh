# Validation roadmap

The roadmap advances only when the preceding milestone has evidence.

## M0 — Protocol skeleton (complete)

- Action, artifact, result, and receipt vocabulary
- Canonical action digests
- In-memory action cache and CAS
- Freshness, producer trust, and integrity rejection reasons
- Portable conformance vector

Exit criterion: independent implementations reproduce the digest vectors.

## M1 — Organization proof of value (protocol and reference implementation complete)

- Persistent local filesystem store
- One organization-backed store
- Shadow mode that reports hits without substituting outputs
- `URL -> bytes` and `HTML -> Markdown` adapter specifications
- Metrics for hit rate, rejected candidates, latency, cost, and bytes transferred
- Versioned evaluation manifests, guarded HTTP execution, JSONL evidence, and
  promotion reports

Exit criterion: a real workload demonstrates savings without an incorrect
substitution during the evaluation window.

Implementation status does not satisfy the exit criterion. M1 remains in
evaluation until measurements from a real workload are recorded.

Evidence recorded on 2026-08-24: a 50-page, two-pass Python documentation
corpus completed 200 shadow evaluations with 100 exact candidate matches and no
mismatches. This validates the public-document pipeline at corpus scale, but it
does not yet establish organization-specific cost savings or long-window
freshness behavior.

## M2 — Safe substitution (reference checklist complete)

- Operation policy registry
- Authorization-partition tests
- Stale-while-revalidate semantics
- Receipt signature profile
- Cross-language conformance suite

Exit criterion: selected read-only operations can use substitution in production
with auditable decisions and a rollback control.

Conditional-validation evidence recorded on 2026-08-24: 100/100 HTTP 304
responses were followed by exact full-response matches, producing 100 immutable
freshness records and zero mismatches. Conditional HTTP is ready for a design
review, not automatic substitution; a live changed-source case and operational
rollback remain outstanding.

Controlled substitution evidence recorded on 2026-08-24: 100/100 operations
substituted after 304 responses and a live environment kill-switch check forced
2/2 operations back to full execution. The substitution path avoided 11.94 MB
of body transfer but was approximately 5.14 seconds slower than the prior full
GET baseline. Conditional HTTP therefore remains disabled by default; the next
economic target is expensive deterministic downstream computation.

Deterministic-computation evidence recorded on 2026-08-24: ten RFC PDFs were
fetched and parsed twice. All 20 second-pass candidates matched exactly with zero
mismatches. PDF layout extraction consumed 327.76 seconds across both passes;
the verified pass showed 183.02 seconds of net reusable parser time. A following
policy-controlled run substituted 20/20 parser actions, returned 11.05 MB from
the verified store, invoked no parser work, and spent 0.49 seconds in lookup.
`document.pdf-to-text/1` is therefore eligible for narrowly scoped exact
substitution; HTTP fetch remains separately governed and disabled by default.

Receipt-signature evidence recorded on 2026-08-24: the
`oncemesh.ed25519/v1` domain-separated Ed25519 profile, strict validator,
immutable memory/filesystem persistence, signed-publication helper, and portable
RFC 8032-seed conformance vector are implemented. Negative tests cover tampered
metadata, wrong keys, non-canonical encodings, unknown fields, and manifest or
producer mismatches.

Signed-admissibility evidence recorded on 2026-08-24: receipt enforcement is now
an explicit per-operation policy gate backed by a reloadable public-key registry.
A required-signature RFC run substituted 20/20 parser actions after full receipt
verification, with 0.58 seconds of combined lookup and verification. A live
revocation run kept the candidate and signature unchanged but marked the key
revoked; substitution stopped immediately and full parsing ran with the audited
reason `receipt_key_revoked`. Rotation overlap, unknown keys, producer denial,
tampering, missing receipts, malformed registries, and policy-untrusted keys have
negative coverage. Production key custody remains deployment work.

Cross-language evidence recorded on 2026-08-24: an independent zero-dependency
Node.js runner passed 20 shared checks covering Unicode canonicalization, four
action identities, source validation, invalid canonical values, receipt digests,
key identifiers, native Ed25519 verification, and tamper rejection. The Python
suite invokes the Node runner when available. Cross-language conformance is
therefore implemented for protocol identity and signed receipts.

Authorization-partition evidence recorded on 2026-08-24: private PDF actions now
use deployment-keyed HMAC-SHA-256 tokens over canonical tenant, scope, and subject
claims. Matching caller/action partitions can substitute; missing, mismatching,
or public-forbidden partitions execute normally. Cross-tenant actions produce
different digests and cannot see each other's candidates. The shared HMAC vector
is reproduced by both Python and Node. Explicit stale-while-revalidate semantics
were the final outstanding reference checklist item.

Stale-while-revalidate evidence recorded on 2026-08-24: the HTTP runtime now has
an explicit bounded SWR mode with exact-action single flight. Tests prove stale
return before refresh, coalescing, 304 validation publication, 200 changed-result
publication, latest trusted freshness selection, fresh-hit bypass, and
synchronous fallback for expired windows, scheduler failure, background failure,
and untrusted producers. Background failures never extend freshness.

The M2 reference checklist is complete: reviewed read-only PDF parsing can use
signed, authorization-partitioned, policy-controlled exact substitution with a
live rollback control and cross-language conformance; HTTP provides guarded
conditional and bounded SWR modes. Organization production rollout still
requires private-key custody, durable operational ownership, and workload-specific
policy approval.

## M3 — Trusted federation experiment

- Availability manifest exchange
- Explicit peer configuration
- Deletion and retention behavior
- Abuse limits and negative trust tests

Exit criterion: two independently operated organizations exchange an explicitly
public artifact without changing its digest or weakening either policy.

Reference evidence recorded on 2026-08-24: two independently configured peers
exchanged an explicitly public result while preserving its action, result, and
artifact digests. Separate availability and production-receipt keys were checked
against receiver policy. Negative coverage includes non-public publication,
unknown trust roots, denied operations and producers, size limits, tampering,
snapshot replay and future timestamps, withdrawal, lease expiry, and attempted
transitive re-export. Python and Node reproduce the shared availability-signature
vector.

The M3 reference implementation is complete. The milestone exit criterion is
not yet met because the recorded peers are not separately operated organizations
over a production network. The initial protocol evidence used in-process calls;
the following evidence advances the transport boundary.

Authenticated-transport evidence recorded on 2026-08-24: an org-b reference
client imported the same class of public immutable bundle from an org-a
reference server across an IPv4 loopback TCP connection. Domain-separated
Ed25519 requests bind peer identity, time, nonce, method, and exact path. Tests
cover unknown receivers, path tampering, stale and future requests, nonce replay
and bounded replay-state exhaustion, timeouts, response limits, and
HTTPS-by-default behavior. Python and Node reproduce the request-signature
vector, bringing the independent runner to 29 shared checks.

This removes the in-process transport limitation from the reference code, but
does not close M3: the two instances still share one machine and operator, and
the loopback pilot deliberately uses the test-only insecure HTTP override.

TLS deployment-harness evidence recorded on 2026-08-24: strict origin and
receiver manifests now drive separate operating-system processes across a
CA-verified TLS connection. Signing seeds remain outside manifests and evidence;
non-public publications, key misbindings, plain HTTP, untrusted certificates,
and evidence overwrites fail closed. The origin bounds concurrency, per-peer
request rate, replay state, and response size. The receiver emits canonical,
secret-free digest evidence.

This is the final locally reproducible M3 preparation. The harness run used one
machine, one operator, and a self-signed test CA, so M3 remains open pending the
same acceptance sequence across two administrative environments with managed
TLS and independent operational sign-off.

Operator-handoff evidence recorded on 2026-08-24: write-once Ed25519 identity
generation, receipt-bound public publication packaging, network-free origin and
receiver preflight, strict templates, and a complete handoff runbook are now
included. Private seeds are never printed or placed in manifests or reports;
publication requires two explicit public-review signals and verifies every
immutable binding before output. Native ACL and secret-manager integration stay
with each operator.

All code-only M3 preparation is complete. Advancing the milestone now requires
external evidence rather than another shared-operator simulation.

Simulated-acceptance evidence recorded on 2026-08-24: three isolated non-root
Linux containers completed the full technical sequence over an internal-only
network and test-CA-verified TLS. The configured receiver preserved every digest;
an unregistered peer was denied; write-once withdrawal stopped new imports; the
prior durable copy survived only through its unexpired lease; real-time expiry
pruned the entry and blob; and public-output scanning found zero secret matches.
All ephemeral keys and containers were destroyed after the run.

The report explicitly records `environment_kind: simulated` and
`administrative_independence: false`. It raises confidence in deployability but
does not alter the external M3 exit criterion.

## M4 — Agent-runtime integration proof

- Framework-neutral execution cache bridge
- Exact runtime namespace and key identity
- Private authorization partitions and explicit producer trust
- TTL, disable, and epoch-based clear behavior
- Thin runtime adapters, beginning with real LangGraph sync and async tests

Exit criterion: the core bridge passes framework-independent safety tests and a
real agent runtime reuses one deterministic node result on an exact second
invocation, while expiry, rollback, corruption, and cross-partition isolation
remain fail-closed.

The normative integration contract is `execution-cache-bridge-v0.md`. M4 is
open until the core, first adapter, and repeatable real-runtime evidence satisfy
that contract.

Reference evidence recorded on 2026-08-24: the framework-neutral core passed
exact identity, TTL, clear, disable, corruption, producer-trust, persisted-epoch,
federation-rejection, and cross-partition tests. A thin adapter against real
LangGraph 1.2.11 reused deterministic node results after one execution in both
synchronous and asynchronous graphs. The repeatable evaluation passed every
check without placing raw tenant identities or serialized values in manifests.

The M4 reference exit criterion is complete for the core and first adapter.
Further frameworks require compatibility adapters and tests, not new cache
identity or policy implementations. Multi-process clearing and performance
benchmarks remain follow-on work.

## M5 — Runtime adapter SDK

- Stable typed-value codec contract
- Shared sync and async lookup, publication, and lookup-or-execute behavior
- Native Python JSON callable integration
- LangGraph adapter delegation to the same SDK
- Explicit boundary for runtimes requiring mutable key enumeration

Exit criterion: two runtime integrations use the same SDK and demonstrate exact
one-execution reuse, serializer binding, failure non-publication, rollback, and
partition isolation without duplicating core policy.

The normative SDK contract is `runtime-adapter-sdk-v0.md`. M5 is open until the
native Python and refactored LangGraph integrations pass shared behavioral and
full regression evidence.

Reference evidence recorded on 2026-08-24: native Python and LangGraph use one
codec-bound runtime adapter SDK. Sync and async Python calls and a real
LangGraph graph each executed once across two exact invocations. Cached nulls
remained hits, operation and encoding failures were not published, serializer
mismatch failed at construction, and shared tests cover expiry, clear, disable,
malformed values, and cross-partition isolation. All Python, Node, and Docker
regressions passed.

The M5 exit criterion is complete. The next adapter boundary is a durable active
key index for runtimes that require enumeration and per-key deletion; that
mutable index must remain distinct from immutable result and artifact storage.

## M6 — Open adapter platform

- Organized `oncemesh.integrations` package with compatibility shims
- Dependency-free adapter registry and bounded optional extras
- Reusable safe codecs and active-key index
- Native Python, LangGraph, LangChain, and LlamaIndex integrations
- Contributor template, authoring contract, and shared safety tests

Exit criterion: four integrations pass their real framework contracts while all
identity, trust, storage, codec, and mutable-index behavior remains centralized,
documented, and reusable by external contributors.

The normative architecture is `adapter-platform-v0.md`. M6 is open until the
package migration, indexed adapter, framework proofs, contributor documentation,
and full regressions are complete.

Reference evidence recorded on 2026-08-24: canonical integration code now lives
under `oncemesh.integrations`; legacy imports are aliases only. Four built-ins
are dependency-light and lazily loadable: native Python, LangGraph, LangChain,
and LlamaIndex. Real framework runs passed alongside shared exact and indexed
conformance probes. The atomic filesystem index preserved active state and
delete generations across reopen, and old immutable values did not resurrect
after overwrite, delete, or re-add.

The authoring guide, runnable template, bounded individual and aggregate extras,
capability registry, opt-in third-party entry points, and reusable probes form
the public contribution surface. All Python, Node, and Docker regressions passed.

The M6 exit criterion is complete. Further adapters can be developed as
independent translation modules. The next platform work is cross-process index
coordination, transactional publication/index commits, and adapter performance
benchmarks under realistic workloads.

## M7 — Cross-process transactional durability

- Cross-platform process locks for filesystem epochs and active-key indexes
- Atomic visibility across immutable publication and active-index commit
- Crash recovery, contention, timeout, reopen, and lost-update proofs
- Extreme mixed-operation stress across the adapter platform

Exit criterion: process crashes and at least 10,000 contended operations preserve
the last committed value, exact generations and epochs, parseable durable state,
and all prior Python, Node, Docker, and real-framework behavior.

The normative contract is `cross-process-transactions-v0.md`.

Reference evidence recorded on 2026-08-24: native Windows and a non-root Linux
container each completed the 11,600-operation extreme profile across 28 spawned
workers—23,200 operations total—with exact epoch and hot-key generation counts.
A forced exit after immutable publication but before index
commit preserved the last committed value; a unique publication ID kept the
orphan unreachable during the next write. All durable JSON parsed after reopen,
no temporary files survived, and lock timeout/recovery behaved as specified.

All 165 Python tests passed with the real LangGraph, LangChain, and LlamaIndex
dependencies; the dependency-light run passed with 9 expected skips. The adapter
evaluations, 29-check independent Node runner, and 20-check isolated Docker
federation regression also passed. M7 is complete for the local filesystem
reference profile. Its measured contention confirms that a SQLite/WAL or
service-backed implementation is the next performance tier for heavy shared use.

## M8 — SQLite/WAL local performance tier

- Standard-library SQLite implementation of `ActiveKeyIndex`
- WAL readers and bounded transactional writers
- Explicit filesystem-index migration with source preservation
- Cross-platform crash, integrity, contention, and performance comparison

Exit criterion: at least 20,000 SQLite-backed cross-process operations preserve
the M7 visibility invariants, pass SQLite integrity checks on Windows and Linux,
materially outperform the JSON index, and leave all adapter and protocol
regressions green.

The normative contract is `sqlite-active-index-v0.md`.

Reference evidence recorded on 2026-08-25: Windows and a non-root Linux
container each completed 20,000 SQLite operations plus a 4,000-operation JSON
baseline. SQLite was 3.756× faster on Windows and 6.109× faster on Linux. Both
platforms preserved exact generation 3999, served readers during an open writer,
recovered a forced exit between immutable publication and commit, and returned
`integrity_check = ok` after 16,000 mixed operations.

Explicit source-preserving JSON migration, bounded busy handling, reopen,
sync/async indexed behavior, `NORMAL`/`FULL` selection, and all failure cases
passed. All 171 Python tests, 9 real adapter checks, 6 runtime SDK checks, 29 Node
checks, and 20 isolated Docker federation checks passed. M8 is complete.

## M9 — Release and real-pilot hardening

- Public `0.1.0` compatibility and package metadata
- Cross-platform CI, clean distributions, and trusted-release workflow
- Security, changelog, release, and support policies
- Strict organization-pilot configuration, daily evidence, and report tooling
- Independent-operator acceptance requirements without simulated promotion

Exit criterion: every code-release gate passes from a clean distribution and
the pilot/attestation tooling fails closed. M9 code preparation can complete
locally; M1 and M3 remain externally gated until real organization and
independent-operator evidence is supplied.

The normative contract is `release-and-pilot-v0.md`.

Reference evidence recorded on 2026-08-25: package version and metadata are
consistent at `0.1.0`; wheel and source distribution pass metadata, content,
secret-scanning, and clean-install checks; cross-platform CI and trusted-release
workflows are defined; security, changelog, release, and pilot operating guidance
are present; and the strict aggregate pilot reporter rejects synthetic evidence,
cross-pilot mixing, duplicate dates, impossible counts, and incomplete gates.

M9 code preparation is complete. Publication, a real organization pilot, and an
independently administered federation pilot are intentionally not claimed. They
require registry/repository authority and evidence produced by external
operators; simulated evidence cannot satisfy those gates.
