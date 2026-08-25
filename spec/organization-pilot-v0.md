# Organization pilot evidence v0

Status: implementation target

An organization pilot has one immutable configuration, one aggregate daily
record per UTC date, and one generated report.

The configuration declares a pseudonymous organization ID, inclusive UTC date
window, minimum observed days, permitted operations, owner role IDs, and numeric
acceptance thresholds. Daily records contain only aggregate counts, durations,
savings, bytes, drill counts, and an evidence digest.

The reporter validates exact fields, dates, non-negative finite values, unique
dates, configured operations, and matching pilot IDs. It sums counters and
durations, computes candidate-hit and error rates, and evaluates every threshold.
Reports are canonical JSON and include a digest over configuration and daily
record digests.

Required fail-closed conditions include missing days, mismatches above the
threshold, incomplete hit comparison, errors above the threshold, insufficient
savings, missing rollback drills, unexpected operations, duplicate dates,
malformed digests, and any simulated environment presented as real.
