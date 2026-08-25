# Authorization partition analysis — 2026-08-24

Private partition identity is now derived with domain-separated HMAC-SHA-256
over canonical tenant, sorted scopes, and optional subject grouping. Only the
opaque token enters `action.vary`; raw claims and the deployment-local partition
key do not enter actions, manifests, receipts, or metrics.

The same claims produce the same token regardless of input scope order. Tenant,
scope, subject grouping, and partition-key changes each produce a different token
and therefore a different PDF action digest.

Policy-controlled runtime tests show that a matching caller/action partition may
substitute, while missing and mismatching context executes normally. Public mode
rejects partitioned actions. A tenant-B action cannot find tenant A's candidate
even when input PDF bytes and parser configuration are identical. HTTP policy
validation cannot silently configure an unsupported required partition, and a
crafted partitioned HTTP action is rejected by public-mode enforcement before
conditional substitution.

Node independently reproduced the HMAC token from the shared conformance vector.
Partition tokens are deliberately not credentials; application and store access
control remain separate requirements.
