# OnceMesh Cross-Language Conformance v0

Status: draft

## 1. Purpose

Cross-language conformance demonstrates that protocol identity and receipt
verification do not depend on Python implementation details. A conforming
implementation consumes the normative JSON vectors without importing OnceMesh
reference code from another language.

## 2. Required positive checks

An implementation must reproduce:

1. every canonical JSON string and action digest in
   `conformance/action-digests-v0.json`;
2. every canonical JSON string and action digest in
   `conformance/pdf-actions-v0.json`;
3. every canonical JSON string and validation digest in
   `conformance/source-validations-v0.json`;
4. every signed receipt digest in `conformance/receipt-signatures-v1.json`;
5. the receipt public-key identifier and Ed25519 signature verification result
   from that receipt vector.
6. every HMAC-SHA-256 token in
   `conformance/authorization-partitions-v1.json`.
7. availability-manifest digest, key identifier, Ed25519 signature, and tamper
   rejection in `conformance/availability-signatures-v0.json`.
8. federation-request digest, key identifier, Ed25519 signature, and tamper
   rejection in `conformance/federation-request-signatures-v0.json`.

Receipt and availability signing inputs must be reconstructed independently by
replacing their signature envelopes with null. Federation request signing uses
the request object directly. Each profile applies its required domain separator.

## 3. Required negative checks

Every value in `conformance/canonicalization-negative-v0.json` must be rejected
before hashing. Implementations must also show that receipt verification fails
after signed metadata changes and when the supplied public key does not match
the envelope key identifier.

## 4. Independence

The implementation may use its runtime's standard cryptographic and UTF-8
libraries. It must not shell out to the Python reference, call a OnceMesh service,
or copy expected computed values into executable source. Expected values are read
only from the shared normative vector files.

## 5. Reference Node runner

`conformance/node/run.mjs` is the independent Node.js implementation. It uses
only `node:crypto`, `node:fs`, `node:path`, and `node:url`. It exits nonzero on
the first failed check and prints a machine-readable report when all checks pass.
