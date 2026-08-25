# OnceMesh Evaluation Run v0

Status: draft
Version identifier: `oncemesh.evaluation/v0`

## 1. Purpose

An evaluation run measures exact reuse opportunities without substituting
cached results. Its manifest makes the workload, network authority, repetition
count, freshness rules, and economic assumptions reviewable before execution.

## 2. Manifest

```json
{
  "spec_version": "oncemesh.evaluation/v0",
  "name": "documentation-smoke",
  "allowed_hosts": ["example.com"],
  "repetitions": 3,
  "request_delay_ms": 200,
  "urls": [
    {
      "url": "https://example.com/",
      "accept": "text/html",
      "freshness_seconds": 3600,
      "estimated_fetch_cost": "0.000000"
    }
  ],
  "promotion": {
    "minimum_candidate_hits": 1,
    "maximum_mismatches": 0,
    "minimum_candidate_match_rate": "1.000000"
  }
}
```

Decimal values are strings under the Action v0 canonical JSON profile.
`allowed_hosts` is an exact, case-insensitive allowlist. Every initial URL and
redirect target must be HTTPS and must name a listed host.

`request_delay_ms` is a non-negative delay before each network execution. It is
an evaluation-run behavior rather than part of the HTTP action identity.

Listing a URL is an assertion by the operator that the evaluation is permitted
to retrieve and process that resource. OnceMesh does not infer permission from
public reachability.

## 3. Pipeline

Each URL is evaluated in manifest order for each repetition:

```text
http.fetch/v1 -> exact response body -> document.html-to-markdown/v1
```

Both operations run in shadow mode and publish locally for later repetitions.
The HTTP response must identify HTML content before the second operation runs.

## 4. Network safety profile

The reference runner:

- permits HTTPS only;
- requires an exact hostname allowlist;
- rejects loopback, private, link-local, multicast, reserved, and unspecified
  resolved addresses;
- rechecks every redirect target;
- bounds redirect count, response bytes, and request time;
- sends no cookies, authorization headers, or ambient application credentials.

Application-level checks cannot completely eliminate DNS rebinding between
validation and connection. Production evaluations should additionally enforce
the same policy at the network boundary.

## 5. Event log

The runner writes one JSON object per operation to an append-only JSONL file.
Each object has version `oncemesh.evaluation-event/v0`. Events contain an
evaluation ID but no URL, action inputs, authorization
partitions, response bytes, or credentials.

An interrupted final line may be ignored by reporting. Any other malformed line
is a report error.

## 6. Promotion decision

The report evaluates only events for the selected evaluation ID. Promotion
passes only when all configured thresholds pass and:

- every candidate hit was checked against execution;
- mismatch count does not exceed the configured maximum;
- candidate matches divided by candidate hits meet the configured rate;
- the minimum candidate-hit sample is present.

The default and recommended mismatch maximum is zero. A passing report permits
design review for a specific operation profile; it does not automatically
enable substitution.

Verified time savings are conservative net estimates: measured execution time
minus measured lookup and artifact-validation time, floored at zero.

Reports have version `oncemesh.evaluation-report/v0` and contain the aggregated
summary, a breakdown by operation profile, individual gate results, and the
final `promotion_review_ready` value.
