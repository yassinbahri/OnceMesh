# OnceMesh Public Reference Operator v0

Status: draft
Depends on: `federation-external-pilot-v0.md`,
`federation-operator-bootstrap-v0.md`, `public-mesh-directory-v0.md`, and
`public-mesh-status-v0.md`

## 1. Purpose

This profile defines the first OnceMesh-operated public federation origin. Its
purpose is to provide independently reachable protocol evidence, a small useful
catalog of reviewed public results, and a deployment template that other
operators can reproduce without inheriting OnceMesh's private keys or trust
decisions.

The reference operator is a distribution service for immutable results. It is
not an arbitrary compute service, an LLM proxy, a prompt-sharing service, a
private cache, or a source of automatic trust.

## 2. Service boundary

The operator MUST:

- serve only publications packaged with classification `public` and an
  affirmative publication review;
- support `oncemesh.federation-http/v0` over publicly trusted HTTPS;
- require signed requests from explicitly enrolled requester identities;
- keep availability, receipt, and requester keys separate by purpose;
- preserve exact action, result, receipt, and artifact digests;
- enforce bounded authentication age, clock skew, replay state, concurrency,
  request rate, and response bytes;
- return the expected unauthenticated denial at `/v0/availability` without
  exposing catalog contents; and
- publish only aggregate, privacy-bounded operational statistics.

The operator MUST NOT:

- execute user-supplied code, prompts, tools, or network requests;
- publish private, tenant-partitioned, licensed, personal, or secret material;
- learn trust keys from requests, responses, or the public directory;
- re-export results imported from another federation peer;
- expose private seeds, TLS private keys, requester identities, nonces,
  per-request logs, source credentials, or raw access telemetry; or
- describe local Docker evidence as independent operation.

## 3. Initial public catalog

The canary catalog SHOULD remain small enough for complete human review. Each
entry MUST have:

1. an immutable action document;
2. an output produced by a deterministic, versioned operation;
3. a signed production receipt from the reference operator;
4. artifact names, sizes, and SHA-256 digests verified during packaging;
5. a documented public source and redistribution basis; and
6. a withdrawal owner and review date.

The recommended first operation is `document.pdf-to-text/1` over a small set of
public standards documents because the repository already has deterministic
adapter, receipt, integrity, and economic evidence for that operation. Test
keys and synthetic evaluation publications MUST NOT be promoted into the public
catalog.

## 4. Requester enrollment

Discovery does not grant use. A receiver operator requests enrollment through a
public, credential-free issue or another documented channel and supplies only a
stable peer identifier and request-purpose public identity. The reference
operator verifies the fingerprint out of band, reviews intended use and rate,
then adds the requester explicitly to a new write-once origin manifest.

Private request seeds remain with the receiver. Removal from a later manifest
revokes new access after the origin restarts. Enrollment records MUST NOT contain
payloads, private keys, tenant data, or request history.

## 5. Deployment profile

The reference deployment MUST run on a Linux host that is administratively
separate from the developer workstation. It MUST use:

- a stable DNS name and publicly trusted, automatically renewed TLS certificate;
- secret-manager or supervisor injection for the availability seed and TLS key;
- a non-root container, read-only root filesystem, dropped Linux capabilities,
  `no-new-privileges`, bounded temporary storage, and bounded process resources;
- read-only mounts for the manifest, certificate chain, public identities, and
  reviewed publications;
- restart supervision, bounded logs, external uptime observation, and alerts;
- encrypted backup of configuration and public publications, excluding replay
  state and temporary files; and
- a documented stop, requester-revocation, publication-withdrawal, and key-
  rotation procedure.

The v0 reference server keeps replay and rate-limit state in one process.
Therefore the deployment MUST run exactly one origin replica. Horizontal
scaling is deferred until those controls have a shared bounded state backend.

## 6. Acceptance gates

Passing a gate does not imply that later gates passed.

### G0 — repository regression

- all dependency-light Python tests pass;
- all optional real-framework adapter tests pass;
- independent Node conformance passes;
- repository and distribution verification pass; and
- the 20-check Docker federation rehearsal passes with its report labeled
  simulated and non-independent.

### G1 — hardened local deployment

- the reference image builds from a clean Docker cache;
- Compose configuration renders without unresolved variables;
- the container runs as non-root with a read-only root filesystem, all Linux
  capabilities dropped, and no secret in the image or rendered configuration;
- offline origin preflight passes; and
- an unconfigured requester receives denial without catalog disclosure.

### G2 — public staging reachability

- public DNS and a trusted TLS chain validate from an external network;
- the directory monitor observes `200` or the expected unauthenticated `401` at
  `/v0/availability` without redirects;
- certificate renewal and service restart are exercised; and
- no management, metrics, or filesystem endpoint is publicly exposed.

### G3 — independent receiver exchange

- a separately administered receiver completes the external federation pilot;
- every action, result, and artifact digest matches the origin record;
- unknown-key denial, withdrawal, and receiver lease expiry pass; and
- both operators retain separate, secret-free evidence and sign off on key
  custody and policy review.

### G4 — directory canary

- the operator profile passes directory schema and semantic validation;
- at least 20 scheduled directory observations produce an aggregate window;
- operator-reported and directory-observed statistics remain distinct; and
- the listing is no stronger than `listed` until directory-controlled evidence
  qualifies it for `observed`.

### G5 — controlled operation

- the canary runs for at least seven days with alerts, bounded storage, and no
  unresolved security event;
- requester revocation, publication withdrawal, service stop, restore, and key
  rotation are exercised; and
- a named owner accepts ongoing patching, incident response, retention, and
  cost responsibility.

## 7. Evidence and privacy

Public evidence MAY include versions, public key fingerprints, public endpoint,
operation identifiers, aggregate request counts, aggregate bytes, availability,
and latency percentiles. It MUST exclude IP addresses, user agents, requester
peer identifiers, nonces, signatures, action parameters, source URLs, result
digests, artifact names, and per-request records from directory statistics.

Security logs retained privately by the operator MUST be access-controlled,
time-bounded, and documented. Public evidence and registration issues MUST be
scanned for seeds, private keys, credentials, and raw artifacts before release.

## 8. Failure and rollback

On unexpected content, digest disagreement, TLS failure, key exposure, abusive
traffic, or evidence leakage, the operator MUST fail closed. The response is:

1. stop the origin or remove the affected requester from a new manifest;
2. withdraw affected publications with a new write-once manifest;
3. rotate exposed keys and independently redistribute new fingerprints;
4. preserve bounded incident evidence without publishing sensitive records; and
5. mark the directory entry `suspended` or `retired` when appropriate.

Previously imported receiver bytes remain governed by receiver retention and
cannot be remotely erased by the origin.

## 9. Deferred behavior

- anonymous federation requests;
- arbitrary community uploads or computation;
- automatic requester enrollment or trust;
- multi-replica origin service;
- a public administration API;
- billing, quotas for sale, or popularity ranking;
- private or organization-partitioned federation; and
- claims of production proof before G3 through G5 have external evidence.
