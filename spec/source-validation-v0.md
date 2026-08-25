# OnceMesh Source Validation v0

Status: draft
Version identifier: `oncemesh.validation/v0`

## 1. Purpose

A source-validation record states that an immutable result was checked against
its authoritative source at a later time. It extends admissible freshness
without modifying the original result manifest or artifact bytes.

## 2. Object

```json
{
  "spec_version": "oncemesh.validation/v0",
  "result_digest": "sha256:<result-manifest-digest>",
  "validated_at": "2026-08-24T15:00:00Z",
  "fresh_until": "2026-08-25T15:00:00Z",
  "producer": "evaluation:local",
  "method": {
    "name": "http.conditional",
    "version": "1",
    "status": 304,
    "etag": "example-etag",
    "last_modified": null
  }
}
```

The record digest is SHA-256 over Action v0 canonical JSON. Records are
immutable and are stored by the digest of the result they validate.

## 3. HTTP conditional profile

The `http.conditional/1` method is valid only when:

- the original result metadata contains an ETag or Last-Modified value;
- a guarded HTTPS request sends the corresponding `If-None-Match` and/or
  `If-Modified-Since` value to the same normalized action URL;
- redirects receive the same allowlist and network checks as full requests;
- the authoritative server returns status 304;
- the validator producer is trusted by the caller.

A 200 response means the candidate was not validated. The new response may be
published as a new result after ordinary execution checks.

Weak ETags are retained exactly. OnceMesh does not reinterpret HTTP validator
semantics.

## 4. Effective freshness

A result is fresh when either its own `fresh_until`, or the `fresh_until` of at
least one trusted validation record for its exact manifest digest, has not
passed. Validation cannot alter the action digest, artifacts, producer, access
control, or operation-specific admissibility.

## 5. Shadow requirement

The initial conditional profile remains shadow-only. After a 304 response, the
reference evaluator performs a full GET and compares the candidate artifacts.
A validation record is published only when the full response matches exactly.
This additional request is an evidence mechanism and may be removed only after
the conditional profile passes its own promotion review.

The reference `revalidate` evaluation consumes an existing
`oncemesh.evaluation/v0` manifest. It evaluates each URL once per configured
repetition, records only the HTTP operation, and requires every 304 response to
be followed by an exact full-response match before recording validation.
