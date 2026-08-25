# Decision 0013: Private authorization partitions use keyed tokens

Status: accepted

## Context

Hashing tenant and scope names without a key would remove raw claims from action
JSON but still permit inexpensive dictionary attacks and cross-organization
correlation. Omitting authorization context entirely risks reusing an artifact
across callers whose read authority differs.

## Decision

Derive authorization partition tokens with domain-separated HMAC-SHA-256 and a
deployment-local key. Bind the token into `action.vary`. Require operation policy
to choose explicitly between public actions and required private partitions.

The runtime compares the action token with caller context before any
application-visible substitution. A failure executes normally and is audited.
Partition tokens never act as credentials.

## Consequences

Tenant, scope, subject grouping, and partition-key changes produce distinct
action digests. Private cache identities are intentionally not portable across
organizations unless they coordinate secret partition keys, which is not
recommended. Outer authorization remains mandatory for remote storage.
