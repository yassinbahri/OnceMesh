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
It reproduces result v1 lineage-manifest and invalidation-record digests from
`derived-lineage-v0.json`.

`public-mesh-directory-v0.json` provides one valid directory and portable
semantic rejection mutations. Run `python scripts/verify_public_directory.py`
to verify both the JSON Schema and reference validation rules.
