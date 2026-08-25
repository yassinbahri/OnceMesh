# ADR 0028: The first public mesh is a bounded reference origin

Status: accepted

## Context

OnceMesh now has a curated public directory and an independently scheduled
reachability monitor, but the directory is intentionally empty. A first-party
operator can provide valuable interoperability evidence and useful immutable
public results. Exposing arbitrary execution, anonymous catalog access, or the
developer workstation would create a much larger security, privacy, abuse, and
operational boundary than the protocol currently supports.

## Decision

Operate the first mesh as a single-replica, allowlisted federation origin on an
independently hosted Linux machine. It serves only affirmatively reviewed,
receipt-signed public publications and retains the existing signed-request,
replay, rate, concurrency, and response bounds.

Keep deployment assets provider-neutral. Default local bindings remain
non-public until an operator deliberately supplies managed DNS, TLS, secret
custody, monitoring, and external acceptance evidence. Do not reuse synthetic
evaluation identities or publications.

## Consequences

- The project can contribute a real endpoint without becoming an arbitrary
  compute or prompt-hosting service.
- Community receivers must enroll a request public key before importing data.
- A single replica is required until replay and rate-limit state can be shared.
- Real DNS, TLS, hosting, key custody, incident response, and cost ownership are
  operational prerequisites rather than properties of Docker Compose.
- The first external receiver closes more of the evidence gap than adding more
  same-host simulation.
