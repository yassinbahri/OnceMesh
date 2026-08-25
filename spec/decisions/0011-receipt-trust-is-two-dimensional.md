# Decision 0011: Receipt trust requires both policy and live key state

Status: accepted

## Context

A signature can remain mathematically valid after a key is compromised or
removed from service. Conversely, placing a key in a global registry should not
authorize it for every operation.

## Decision

Receipt admission requires two independent grants:

1. the operation policy explicitly trusts the receipt key identifier; and
2. the reloadable key registry marks that key active and authorizes the manifest
   producer.

Either source may disable substitution. Registry revocation always wins. Key
rotation uses an overlap in which old and new identifiers are trusted and active
simultaneously. Unknown and removed keys fail closed.

Receipt enforcement is opt-in per operation. Once marked `required`, missing or
invalid signature authority can never downgrade to unsigned substitution.

## Consequences

Operation owners control scope while security operators retain immediate key
revocation. Every decision performs additional local reads and signature
verification. Historical acceptance of retired keys is intentionally deferred.
