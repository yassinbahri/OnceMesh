# Decision 0014: A stale return requires accepted refresh work

Status: accepted

## Context

Returning stale content without ensuring a refresh attempt can turn a bounded
optimization into indefinite staleness. Starting one thread per caller creates
origin load spikes and races between new result publications.

## Decision

Authorize SWR only through a dedicated HTTP policy mode with an explicit maximum
stale age. Require an injected coordinator to accept or coalesce background work
before returning stale bytes. Coordinate by exact action digest so concurrent
callers produce at most one conditional request per process.

Background 304 responses create validation records; background 200 responses
publish new results. Failures publish neither. Synchronous execution remains the
fail-closed path whenever eligibility or scheduling fails.

## Consequences

Applications can trade bounded freshness for lower tail latency with an auditable
policy. The in-process reference coordinator is not durable or distributed;
production deployments may replace it without changing runtime eligibility
semantics.
