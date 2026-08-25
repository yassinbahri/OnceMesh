# Contributing to OnceMesh

OnceMesh follows a specification-driven workflow.

Contributions can extend the protocol, add an adapter or codec, implement a
storage/index backend, reproduce measurements, improve operations, or make the
project easier to understand. The [practical guide](docs/user-guide.md#help-build-the-open-mesh)
explains each path and the boundaries between public, private, organization, and
federated reuse.

## Before opening a pull request

1. Open or link an issue for behavior that changes the protocol, safety model,
   public API, or interoperability contract.
2. Keep one pull request focused on one reviewable outcome.
3. Add the specification or decision record before implementation when behavior
   changes.
4. Include tests for the successful path and the unsafe or rejected boundary.
5. Record measured results and limitations for performance claims.

Documentation fixes and additional tests that do not change behavior can go
directly to a focused pull request.

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

## Other high-value contributions

- Independent conformance runners in Go, Rust, JavaScript, or other languages.
- Store and `ActiveKeyIndex` implementations for production infrastructure.
- Secret-manager, monitoring, deployment, backup, and retention integrations.
- Reproducible shadow evaluations with content-free aggregate evidence.
- Threat-model review, failure-path tests, and independent federation pilots.
- Public mesh registrations and privacy-preserving aggregate statistics that
  follow `spec/public-mesh-directory-v0.md`.

The project welcomes negative results. Evidence that a reuse profile is slower,
too expensive, nondeterministic, or unsafe helps keep the mesh trustworthy.
