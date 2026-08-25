# Stale-while-revalidate analysis — 2026-08-24

The reference HTTP runtime now supports an explicit bounded
`stale-while-revalidate` policy mode. A trusted, integrity-checked result is
returned stale only when its latest trusted freshness boundary is inside the
configured stale window and refresh work is accepted or coalesced by an injected
coordinator.

Deferred-coordinator tests prove that stale bytes return before the conditional
network request begins. A background 304 creates an immutable validation record;
a background 200 publishes a new result; an exception or unexpected status
publishes neither and does not extend freshness. Fresh candidates return without
background work, while expired windows, missing or failed coordinators, missing
publish authority, and untrusted refresh producers execute synchronously.

The in-process coordinator provides exact-action single flight: two concurrent
callers can receive the same eligible stale result, but only one conditional
request runs. Its key is released after both successful and failed work so later
calls can retry. Action and candidate data are snapshotted before submission, and
reference metrics sinks and the memory store are thread-safe.

This mode deliberately permits bounded stale responses and remains disabled in
the active evaluation policies. The included example policy has a five-minute
window. Durable queues and distributed single flight remain deployment concerns.
