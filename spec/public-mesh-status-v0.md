# OnceMesh Public Mesh Status v0

Status: draft
Version identifier: `oncemesh.public-mesh-status/v0`

## 1. Purpose

The public mesh status snapshot records recent, independently initiated network
observations for entries in the curated public mesh directory. It powers the
human-facing directory without changing the reviewed registry document.

A status observation is operational evidence only. It **MUST NOT** grant trust,
authorize federation, validate an operator, prove result correctness, or create
a service-level guarantee.

## 2. Probe behavior

For each `listed` or `observed` entry, the reference monitor performs one
unauthenticated HTTPS `GET` to `<endpoint>/v0/availability` per scheduled run.
The probe:

- uses a five-second timeout and reads at most 4 KiB;
- sends no cookies, credentials, signatures, proxy settings, or private data;
- follows no redirects;
- permits only the exact host already present in the validated directory;
- rejects hosts resolving to non-global IP addresses; and
- records no resolved IP address, response body, header value, or exception
  text.

An HTTP `200` or `401` response is `up`: `200` is a public response and `401` is
the expected response from an authenticated OnceMesh origin when no request
signature is supplied. Another HTTP response is `degraded`, because HTTPS was
reachable but the expected protocol response was not observed. DNS, connection,
timeout, or TLS failure is `down`. Suspended and retired entries are
`not_checked`.

This classification measures reachability, not the success of a real authorized
federation exchange. Response time includes DNS, TCP, TLS, request, and response
header latency from the hosted runner's location.

## 3. Snapshot document

A snapshot has exactly:

- `spec_version`: `oncemesh.public-mesh-status/v0`;
- `generated_at`: canonical UTC time for the monitoring run;
- `monitor`: fixed public methodology metadata; and
- `meshes`: observations sorted by `peer_id`, with exactly one item for each
  registry entry.

Each observation contains the registry `peer_id` and `registry_status`, its
`state`, nullable `checked_at`, `response_time_ms`, and `http_status`, plus one
bounded public `detail` code. Response time is a non-negative integer rounded to
the nearest millisecond. It is present whenever an HTTP response was received.

The snapshot **MUST** correspond to the exact directory supplied to the monitor:
peer identifiers, ordering, and registry status values must match.

## 4. Publication

GitHub Actions produces a new snapshot on a bounded schedule and deploys it only
inside the GitHub Pages artifact. Routine observations are not committed to the
repository, avoiding noisy history and preventing the monitor from rewriting
the curated registry.

The Pages interface must display the observation time and methodology, preserve
the registry status separately, handle missing or stale snapshots explicitly,
and avoid ranking operators by latency.

## 5. Limits and non-goals

The reference run is bounded to 500 active meshes with at most eight concurrent
requests. A larger active directory fails closed until maintainers deliberately
revise the monitoring architecture.

The monitor does not perform authenticated availability retrieval, bundle
downloads, semantic checks, throughput tests, geographic comparisons, incident
notification, historical retention, or automatic registry suspension.
