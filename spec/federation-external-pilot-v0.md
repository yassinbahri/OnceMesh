# OnceMesh External Federation Pilot v0

Status: draft
Depends on: `federation-experiment-v0.md`, `federation-http-transport-v0.md`

## 1. Objective

The pilot closes M3 only when two separately administered organizations exchange
one affirmatively public immutable result over managed TLS while the receiver
preserves the origin action, result, and artifact digests and applies its own
trust policy without exceptions.

## 2. Separation requirements

The origin and receiver must have different operational owners. Each owner:

- generates and retains its own private keys;
- distributes only raw public keys and stable peer identifiers out of band;
- reviews its local configuration independently;
- runs its own process in its own administrative environment;
- retains its own logs and signs off on the resulting digest comparison.

Private seeds must not appear in deployment manifests, command arguments,
evidence, or logs. Reference commands read 32-byte seeds from named environment
variables as canonical unpadded base64url. Production secret injection may use a
supervisor or secret manager while preserving the same process interface.

## 3. Origin prerequisites

The origin prepares:

- a DNS name and managed TLS certificate whose private key remains local;
- an availability signing key;
- the receiver peer identifier and request-signing public key;
- a reviewed public publication containing the exact action, manifest,
  production receipt, and artifacts;
- response, authentication-window, replay-state, concurrency, and request-rate
  limits.

The origin must verify artifact integrity and the production receipt before
starting. Startup fails if any publication is not explicitly `public`.

## 4. Receiver prerequisites

The receiver prepares:

- the HTTPS origin URL and trusted CA chain;
- its request-signing key;
- the exact origin peer identifier and availability public key;
- independently approved production-receipt keys, producers, and operations;
- entry, artifact, transfer, availability-age, response-size, timeout, and local
  retention limits;
- the exact requested action.

No trust material may be learned from the HTTP response.

## 5. Required evidence

Each receiver run emits one `oncemesh.federation-pilot-report/v0` JSON object
containing:

- run identifier and UTC observation time;
- origin and receiver peer identifiers;
- HTTPS origin with query and user information absent;
- requested action digest;
- advertised and imported result digest;
- imported artifact names, digests, and byte sizes;
- the receiver's non-secret policy limits;
- outcome and reason;
- TLS enabled, digest preservation, and local-policy-enforcement booleans.

The report must never contain private keys, raw artifact bytes, authentication
signatures, nonces, HTTP authorization headers, or environment-variable values.
An origin operator separately confirms that the reported result and artifact
digests equal its publication record.

## 6. Acceptance gate

M3 passes only if:

1. the receiver reports `imported` over HTTPS;
2. action, result, and every artifact digest match the origin record;
3. both organizations confirm separate key custody and policy review;
4. a deliberate unknown-key request is denied without catalog disclosure;
5. withdrawal prevents a new receiver import;
6. receiver lease expiry removes its imported cache entry;
7. no policy limit or TLS verification override was used.

A localhost, shared-operator, self-signed, or insecure-HTTP run is useful test
evidence but cannot satisfy this gate.

Withdrawal is represented by a new write-once origin manifest with the selected
result removed, followed by an origin restart. An empty publication list is
valid after the final result is withdrawn. Previously imported receiver bytes
remain governed by their durable local lease.

## 7. Abort conditions

Abort the pilot on unexpected publication content, certificate validation
failure, digest disagreement, missing receipt trust, repeated authentication
failures, limit exhaustion, or evidence containing secret material. Do not
weaken a policy to turn a miss into a hit; resolve configuration out of band and
start a new run identifier.
