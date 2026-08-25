# OnceMesh Federation Operator Bootstrap v0

Status: draft
Depends on: `federation-external-pilot-v0.md`

## 1. Purpose

This bootstrap procedure lets each pilot operator create signing identities,
package one reviewed public result, and verify local deployment material before
contacting the other organization. It must not turn local convenience into
implicit trust or publication authority.

## 2. Signing identity generation

`oncemesh-federation keygen` creates a random 32-byte Ed25519 seed using the
operating system cryptographic random source. The operator supplies a peer
identifier, one purpose (`availability`, `request`, or `receipt`), a new private
seed path, and a new public identity path.

Both paths are write-once: existing files are never replaced. The private seed
file contains canonical unpadded base64url and is created with owner-only mode
where the platform honors POSIX modes. The public identity contains only:

- `spec_version: oncemesh.federation-identity/v0`;
- peer identifier and key purpose;
- `oncemesh.ed25519/v1` profile;
- SHA-256 key identifier;
- raw public key as canonical unpadded base64url.

The command prints only the public identity. It never prints the private seed.
The private file is bootstrap material for transfer into the operator's secret
manager or supervisor environment. Windows and shared-filesystem operators must
apply and audit native ACLs because portable file modes do not express those
access-control systems.

## 3. Public publication packaging

`oncemesh-federation package-publication` requires exact action, result manifest,
signed production receipt, receipt public identity, and one named file per
manifest artifact. It verifies:

- action and result structure and exact digest binding;
- receipt key identifier, signature, result digest, and producer binding;
- artifact name set, size, and SHA-256 digest;
- explicit `--classification public` and `--confirm-publication-review` flags;
- a new output path.

The output is canonical `oncemesh.federation-publication/v0` JSON with artifact
bytes encoded as unpadded base64url. Packaging does not decide whether content is
legally, contractually, or ethically public; the affirmative review remains an
operator responsibility.

## 4. Offline preflight

`preflight-origin` and `preflight-receiver` load the same manifests used by the
network commands but make no peer request.

Origin preflight verifies secret availability, TLS certificate/key loading,
configured key bindings, public publication integrity, receipt signatures, and
all limits. Receiver preflight verifies secret availability, CA loading, HTTPS
origin form, trust mappings, action structure, evidence-path freshness, and all
limits.

Preflight output contains public identities, digests, counts, endpoints, and
limits only. It never contains seeds, raw artifacts, request signatures, or
nonces. A successful preflight is necessary but not sufficient for the external
pilot acceptance gate.

## 5. Handoff sequence

1. Each operator generates its own identities and moves private seeds into local
   secret custody.
2. Operators exchange public identity JSON through an authenticated out-of-band
   channel and verify key identifiers independently.
3. The origin packages and reviews the public result.
4. Both operators complete offline preflight and exchange only the reports.
5. The origin starts the TLS service; the receiver runs one new probe ID.
6. Both compare the receiver evidence to the origin publication digests.
7. They test unknown-key denial, withdrawal, and receiver lease expiry.

## 6. Failure behavior

Generation, packaging, and evidence outputs never overwrite existing files.
Malformed JSON, duplicate keys, missing secrets, invalid TLS material, mismatched
key identifiers, receipt failure, artifact mismatch, non-public classification,
or missing review confirmation aborts without producing an output artifact.
