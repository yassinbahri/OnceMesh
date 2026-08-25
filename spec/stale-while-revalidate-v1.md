# OnceMesh HTTP Stale-While-Revalidate v1

Status: draft
Method identifier: `oncemesh.http-stale-while-revalidate/v1`

## 1. Purpose

Stale-while-revalidate (SWR) may reduce request latency by returning a boundedly
stale HTTP result while refreshing it asynchronously. It deliberately permits a
short interval in which application-visible bytes may differ from the current
origin. It is therefore a separate, explicit policy mode and is never inferred
from ordinary freshness metadata.

## 2. Eligibility

An HTTP result may be returned stale only when all conditions hold:

1. `http.fetch/1` policy mode is `stale-while-revalidate`.
2. The exact action candidate passes producer trust and artifact integrity.
3. The candidate comes from an allowed tier.
4. The latest trusted freshness boundary is present and expired by no more than
   `max_stale_seconds`.
5. Candidate metadata contains an ETag or Last-Modified validator.
6. Authorization partition policy passes.
7. A background revalidation coordinator accepts or has already accepted the
   exact action digest as an in-flight job.
8. The background producer is trusted for both source-validation records and new
   result manifests, covering the possible 304 and 200 outcomes.

If any condition fails, OnceMesh executes the HTTP operation synchronously and
returns that execution result. A stale result without scheduled or coalesced
revalidation must never be returned.

## 3. Latest trusted freshness boundary

The boundary is the latest of:

- the immutable result manifest's `fresh_until`; and
- any source-validation `fresh_until` issued by a producer trusted under the
  operation policy.

Malformed, unreadable, untrusted, or unrelated validation records do not extend
the boundary. Future boundaries make the candidate fresh and route through the
ordinary policy behavior rather than SWR.

## 4. Single-flight concurrency

The coordinator keys jobs by exact action digest. At most one background job for
that digest may execute in one coordinator instance. Concurrent callers may all
receive the same eligible stale result, but only the first schedules work; later
callers record a coalesced revalidation.

The in-flight key must be released in a `finally` path after success or failure.
A later call can then retry. Different action digests may refresh concurrently.

The runtime snapshots mutable action and candidate structures before submission.
Injected transports, metrics sinks, and stores must support calls from coordinator
workers. The reference sinks and stores provide in-process thread safety.

## 5. Background revalidation

The job performs a guarded conditional GET with the selected result's validators:

- HTTP 304 publishes an immutable source-validation record with a freshness
  interval capped by `max_validation_ttl_seconds`.
- HTTP 200 publishes the changed response as a new immutable result manifest.
- Any other status or exception publishes nothing and retains no freshness.

The already-returned stale response is not retroactively changed. Background
failures must be observable but must not extend freshness or the stale window.

## 6. Audit behavior

A stale return records `stale_while_revalidate` and whether background work was
scheduled or coalesced. Required synchronous fallback reasons include
`revalidation_scheduler_missing`, `stale_freshness_missing`,
`stale_window_exceeded`, `validator_missing`, `refresh_producer_untrusted`, and the existing candidate, tier,
policy, authorization, and kill-switch reasons.

Avoided latency and cost for stale returns are estimates, not verified savings,
because the background origin result is not available at return time.

## 7. Non-goals

v1 does not provide distributed single-flight coordination, durable job queues,
automatic retries, stale-if-error, mutation suppression, or guarantees that a
background thread survives process termination. Deployments requiring those
properties must inject a durable coordinator with equivalent submit semantics.
