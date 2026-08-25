# Release process

## Candidate preparation

1. Update `CHANGELOG.md`, `pyproject.toml`, and `oncemesh.__version__` to the same
   Semantic Versioning value.
2. Confirm protocol changes have explicit spec versions and vectors.
3. Run repository hygiene, static analysis, coverage, schema validation, and the
   live dependency vulnerability audit.
4. Run both dependency-light and full-adapter tests, Node conformance, package
   verification, and Docker federation acceptance.
5. Build from a clean checkout with `python -m build` and validate with
   `python -m twine check dist/*`.
6. Install the wheel into a clean environment and run the import/CLI smoke test.
7. Inspect sdist and wheel contents for secrets, caches, private evidence, and
   unintended payloads.

## Publishing

Create an annotated `vX.Y.Z` tag only after CI passes. The tag must exactly match
the package and runtime version. GitHub's protected `pypi` environment and PyPI
trusted publishing perform the upload without a long-lived API token.

The release workflow must not be enabled for a new repository until its PyPI
project ownership, trusted publisher, protected environment reviewers, and tag
protection are configured by the owner.

## Compatibility

Patch releases preserve Python API compatibility. During `0.x`, minor releases
may change APIs with changelog and migration notes. Immutable protocol versions
never change meaning; incompatible wire behavior gets a new `spec_version`.
