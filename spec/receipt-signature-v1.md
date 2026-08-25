# OnceMesh Receipt Signature Profile v1

Status: draft
Profile identifier: `oncemesh.ed25519/v1`

## 1. Purpose

This profile makes a result-production receipt independently verifiable. It
authenticates the signing key and exact receipt bytes. It does not prove that an
executor was correct, that an operation was safe to substitute, or that the
signer is trusted by a caller.

The signature algorithm is Ed25519 as specified by RFC 8032.

## 2. Receipt object

```json
{
  "spec_version": "oncemesh.receipt/v0",
  "result_digest": "sha256:<64 lowercase hex characters>",
  "producer": "evaluation:local",
  "executor_environment": {
    "implementation": "oncemesh-python",
    "platform": "windows/amd64"
  },
  "signature": {
    "profile": "oncemesh.ed25519/v1",
    "key_id": "sha256:<digest of the raw 32-byte public key>",
    "value": "<unpadded base64url encoding of the 64-byte signature>"
  }
}
```

All object fields are exact: unknown or missing fields are invalid. The
`executor_environment` value is a canonical-JSON object and must contain only
non-secret production metadata. Producer identity, private inputs, filesystem
paths, access tokens, and host secrets must not be inferred from or added to it.

## 3. Signing input

To construct the signing input:

1. Copy the complete receipt and replace `signature` with JSON `null`.
2. Encode that object with the OnceMesh v0 canonical JSON profile.
3. Prefix the bytes with the ASCII domain separator followed by NUL:
   `OnceMesh receipt signature v1\x00`.

The Ed25519 signature is computed over those exact bytes. Signing the ordinary
serialized JSON or a receipt with the signature envelope present is invalid.

## 4. Key and envelope encoding

- Public keys are the 32-byte RFC 8032 Ed25519 encoding.
- `key_id` is the OnceMesh SHA-256 digest of those raw public-key bytes.
- Signatures are exactly 64 bytes.
- `value` uses the RFC 4648 URL-safe base64 alphabet without `=` padding.
- Non-canonical base64 encodings are rejected.

Private keys are never stored in receipts, policies, or content stores. Key
generation, encrypted private-key storage, rotation, revocation, and identity
discovery are deployment responsibilities outside this profile.

## 5. Verification

A verifier must:

1. validate the exact receipt structure and canonical value restrictions;
2. resolve the configured public key for `key_id`;
3. recompute the public-key digest and compare it to `key_id`;
4. reconstruct the domain-separated signing input;
5. verify the Ed25519 signature;
6. separately require that `result_digest` equals the selected result manifest
   digest and `producer` equals the manifest producer.

Malformed envelopes, unknown keys, digest mismatches, invalid signatures, and
receipt-to-manifest mismatches all fail closed.

## 6. Trust boundary

A cryptographically valid receipt proves possession of a private key associated
with `key_id`. The caller still decides whether that key and producer are trusted
for the operation. Receipt verification never replaces action equality,
freshness, authorization, allowed-tier, replay-safety, or artifact-integrity
checks.

## 7. References

- RFC 8032, Edwards-Curve Digital Signature Algorithm (EdDSA):
  https://www.rfc-editor.org/rfc/rfc8032
- RFC 4648, Base Encodings: https://www.rfc-editor.org/rfc/rfc4648
