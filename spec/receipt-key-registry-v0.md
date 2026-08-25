# OnceMesh Receipt Key Registry v0

Status: draft
Version identifier: `oncemesh.key-registry/v0`

## 1. Purpose

The receipt key registry maps trusted receipt key identifiers to raw Ed25519
public keys and current lifecycle state. It is an operational trust input, not a
portable artifact and not part of an action digest.

## 2. Registry document

```json
{
  "spec_version": "oncemesh.key-registry/v0",
  "keys": {
    "sha256:<public-key digest>": {
      "profile": "oncemesh.ed25519/v1",
      "public_key": "<unpadded base64url raw 32-byte public key>",
      "status": "active",
      "producers": ["evaluation:local"]
    }
  }
}
```

All fields are exact. Each map key must equal the SHA-256 digest of the decoded
32-byte public key. `producers` is the complete set of producer identities that
the key is permitted to authenticate.

Supported states are `active`, which permits policy-authorized verification, and
`revoked`, which must never be admitted even if policy still lists the key.

## 3. Reload and failure behavior

The registry is re-read for every substitution decision. Missing, unreadable,
malformed, unsupported, or internally inconsistent registries fail closed to
ordinary execution when a receipt is required.

An unknown key, revoked key, producer mismatch, invalid signature, missing
receipt, or receipt-to-manifest mismatch also fails closed. No failure may fall
back to unsigned substitution.

## 4. Rotation

Rotation uses an overlap window:

1. Add the new key as `active` and add its key identifier to relevant operation
   policies while the old key remains active.
2. Publish new results with the new key.
3. After migration, mark the old entry `revoked` and remove it from policies.

Multiple active keys are expected during rotation. Revocation takes effect on
the next operation because policy and registry are reloaded for every decision.
Removing a key makes it unknown and also fails closed. v0 provides no historical
or time-scoped acceptance of retired keys.

## 5. Private keys

Private keys never appear in this registry. Their generation, encrypted storage,
access control, rotation, backup, and destruction are deployment responsibilities.
