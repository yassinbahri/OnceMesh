# OnceMesh conformance vectors

These files are normative examples for implementations. A conforming v0 action
implementation must reproduce every `canonical_json` byte sequence and
`action_digest` in `action-digests-v0.json`.

New edge cases should be added here before changing canonicalization code.

Run `node conformance/node/run.mjs` for the independent Node.js implementation.
It also verifies source-validation digests, PDF actions, negative canonicalization
vectors, receipt digests, and Ed25519 receipt signatures without importing the
Python reference implementation.
The runner also reproduces the keyed authorization-partition vector.
