# OnceMesh Public Mesh Directory v0

Status: draft
Version identifier: `oncemesh.public-mesh-directory/v0`

## 1. Purpose

The public mesh directory is a curated catalog that helps people discover
operators offering OnceMesh public-federation endpoints. It carries public
operator metadata, capabilities, public signing identities, and bounded
aggregate statistics.

Directory discovery is informational. Listing, search rank, status, a successful
health check, or possession of a listed key **MUST NOT** create federation trust,
authorize a request, import a result, or modify local peer configuration.

## 2. Directory document

A directory document has exactly these fields:

```json
{
  "spec_version": "oncemesh.public-mesh-directory/v0",
  "generated_at": "2026-08-25T08:15:00Z",
  "directory": {
    "name": "OnceMesh Community Directory",
    "repository": "https://github.com/yassinbahri/OnceMesh",
    "policy_url": "https://github.com/yassinbahri/OnceMesh/blob/main/directory/README.md"
  },
  "meshes": []
}
```

`generated_at` identifies the snapshot and **MUST** be canonical UTC. `meshes`
is bounded to 10,000 entries and sorted by `peer_id` in the canonical repository
snapshot. Peer identifiers and HTTPS endpoints **MUST** be unique.

## 3. Mesh profile

Each profile contains exactly:

- `peer_id`: stable federation peer identifier;
- `display_name` and `description`: public presentation text;
- `operator`: public operator name and HTTPS website;
- `endpoint`: the HTTPS federation base URL, without credentials, query, or
  fragment;
- `regions`: public service-region or jurisdiction labels;
- `status`: `listed`, `observed`, `suspended`, or `retired`;
- `protocols`: supported immutable OnceMesh protocol identifiers;
- `operations`: advertised public operation name, version, and output schema;
- `availability_identity`: the origin's public availability-signing identity;
- `receipt_identities`: public receipt-signing identities advertised by the
  operator;
- `stats`: null or one aggregate statistics window; and
- `submitted_at`: canonical UTC profile-submission time.

The identity `peer_id` **MUST** equal the profile `peer_id`. Every public key is
canonical unpadded base64url, its identifier is the SHA-256 digest of the raw
32-byte Ed25519 public key, and identity purposes are enforced.

The directory exposes keys to help an operator compare fingerprints. A client
**MUST NOT** copy them into a trusted configuration automatically. Trust requires
an explicit local decision and an authenticated out-of-band key check.

## 4. Status semantics

- `listed`: schema, uniqueness, public classification declaration, and
  repository review passed. No uptime claim is made.
- `observed`: a directory-controlled probe reached the advertised public
  endpoint during the attached statistics window. This is connectivity evidence
  only, not a security or result-quality endorsement.
- `suspended`: the entry remains visible for warning and audit purposes but
  should not be selected for a new pilot.
- `retired`: the operator declared the endpoint permanently withdrawn.

Search results **MUST** show status and **MUST NOT** silently omit suspended or
retired entries when the user explicitly requests them.

## 5. Aggregate statistics

Statistics are optional and have exactly:

- `evidence_kind`: `operator-reported` or `directory-observed`;
- canonical UTC `window_started_at`, `window_ended_at`, and `observed_at`;
- `sample_size`, at least 20;
- `successful_requests` and `bytes_served`, non-negative integers;
- `availability_ratio`, a canonical six-decimal string from `0.000000` through
  `1.000000`; and
- `latency_ms.p50` and `latency_ms.p95`, non-negative decimal strings with p95
  greater than or equal to p50.

The window end must be after its start, `observed_at` must not precede the
window, successful requests must not exceed sample size, and an `observed`
profile requires `directory-observed` statistics.

Statistics **MUST NOT** contain source URLs, action or result digests, operation
inputs, artifact names or contents, request identities, tenant identifiers,
authorization partitions, credentials, IP addresses, or per-request records.
They are historical observations, not service-level guarantees.

## 6. Repository and submission model

The canonical v0 directory is `directory/public-meshes.json`. Operators submit
profiles through a pull request or the public-mesh registration issue template.
CI validates schema, semantic invariants, ordering, and duplicate identifiers.

Maintainers may mark an entry suspended when its endpoint is unsafe,
misrepresented, repeatedly unavailable, or associated with abuse. Repository
history preserves the disposition. Security reports follow `SECURITY.md`.

## 7. Network safety

The reference discovery client reads the reviewed local document by default.
Fetching a newer snapshot is explicit and limited to the canonical HTTPS
directory URL. Reads use no cookies, authorization headers, proxy credentials,
or ambient application credentials; redirects, time, and response bytes are
bounded; and non-global resolved addresses are rejected.

The discovery client **MUST NOT** probe mesh endpoints. Independent probing is a
separate, future service with its own authority, rate, privacy, and abuse model.

## 8. Deferred behavior

- automatic trust or peer configuration;
- decentralized, DHT, DNS, or gossip discovery;
- ranking by popularity or traffic;
- per-request telemetry;
- public submission without maintainer review;
- real-time monitoring or availability guarantees;
- private artifact discovery or federation; and
- transitive trust between listed peers.
