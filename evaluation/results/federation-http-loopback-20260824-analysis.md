# Authenticated federation HTTP pilot analysis — 2026-08-24

An org-b reference client imported an explicitly public result from an org-a
reference server over IPv4 loopback HTTP. The client authenticated each request
with its configured Ed25519 key. The result crossed a real TCP connection and
retained the origin action, result, and artifact digests exactly.

Request signatures bind receiver identity, timestamp, random nonce, method,
exact path, and empty-body digest. Tests reject unconfigured receivers, altered
paths, stale and future timestamps, reused nonces, and requests that exceed the
bounded replay cache. Client tests enforce timeouts, raw response limits, JSON
content type, no compression, strict decoding, and no redirects. HTTPS is the
default; plain HTTP requires an explicit loopback-only override.

The Ed25519 request vector is independently reproduced by Python and Node.js.
Transport authentication remains separate from signed origin availability and
signed production receipts, so a successful import crosses three independent
trust checks.

This pilot improves the M3 evidence from an in-process protocol call to a real
localhost TCP exchange. It still does not meet the milestone's independently
operated-organization criterion. The next valid evidence must use managed TLS,
separate operational key custody, externally configured peers, and production
rate and concurrency controls across two administrative environments.
