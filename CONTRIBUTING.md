# Contributing to OnceMesh

OnceMesh follows a specification-driven workflow.

## Proposing behavior

Open a proposal that states:

1. The user-visible behavior.
2. The safety or interoperability invariant.
3. At least one accepted example.
4. At least one rejected or boundary example.
5. Compatibility impact on existing v0 objects.

For a significant design choice, add an ADR under `spec/decisions`. Modify the
normative specification and conformance data before modifying implementation
code.

## Definition of done

- Normative language is unambiguous.
- Schemas agree with the prose.
- Conformance vectors cover observable wire behavior.
- The reference implementation passes all vectors.
- Failure behavior is tested, especially where an unsafe hit could occur.
- Deferred behavior remains explicitly out of scope.

## Release checks

Pull requests run the core suite across supported Python versions on Windows and
Linux, the optional adapter contracts, independent Node conformance, clean wheel
and source-distribution installation, and the isolated Docker federation
rehearsal. Run the relevant local checks described in [`docs/release.md`](docs/release.md)
before submitting a change.

Release artifacts must not contain evaluation results, caches, signing seeds, or
private keys. Pilot results are evidence, not implementation fixtures: synthetic
reports must remain labeled synthetic, and no contributor may present them as
real-organization or independent-operator acceptance.

## Contributing an adapter

Adapters live under `src/oncemesh/integrations` and must delegate shared
identity, storage, trust, freshness, codec, and mutable-index behavior rather
than copying it. Start with
[`docs/adapters/authoring.md`](docs/adapters/authoring.md) and the runnable
[`examples/custom_runtime_adapter.py`](examples/custom_runtime_adapter.py).

Every adapter needs a dependency-free registry descriptor, an individual
optional dependency extra, shared conformance probes, native contract tests, and
at least one real framework workflow test. Compatibility shims contain imports
only and must never become a second implementation.
