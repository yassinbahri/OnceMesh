# Release and organization pilot v0

Status: implementation target

## Purpose

This contract separates release readiness from external production evidence.
OnceMesh may publish a `0.x` package after its code-release gates pass. It MUST
NOT claim organization proof of value or independent federation merely because
local, container, or synthetic evidence passes.

## Version and compatibility

- The first public development release is `0.1.0`.
- Package versions follow Semantic Versioning.
- During `0.x`, a minor release may change Python APIs with migration notes; a
  patch release must remain backwards compatible.
- Published protocol `spec_version` values and immutable digests do not inherit
  package-version latitude. Any incompatible wire change requires a new explicit
  spec version and conformance vectors.
- Public imports listed in `oncemesh.__all__`, console entry points, schemas, and
  adapter entry-point groups form the compatibility surface.

## Code-release gate

A release candidate requires:

1. Apache-2.0 license text, package metadata, changelog, security policy, and
   release instructions;
2. clean sdist and wheel builds with metadata validation;
3. clean-install smoke tests from the wheel;
4. core tests on Windows and Linux for Python 3.11 through 3.13;
5. real optional-adapter tests, Node conformance, and Docker federation tests;
6. package version equal to the release tag; and
7. no secrets or organization payloads in distribution artifacts.

Publishing uses a protected environment and PyPI trusted publishing. A local
workspace may build a candidate but cannot satisfy repository protection or
package-registry ownership.

## Organization pilot evidence

Pilot configuration and daily records use the strict formats defined in
`organization-pilot-v0.md`. Evidence contains aggregate metrics and digests, not
customer payloads, raw tenant identifiers, credentials, or private keys.

A pilot is externally reviewable only when:

- its configured minimum number of distinct UTC dates is present;
- every daily record belongs to the same pilot and falls inside the window;
- evaluation, mismatch, error, latency, savings, and kill-switch thresholds pass;
- workload, security, and operations owners are named by pseudonymous role IDs;
- the report identifies the environment as real rather than simulated; and
- the report digest is preserved for sign-off.

Synthetic fixtures may test the reporter but MUST set `environment_kind` to
`synthetic` and can never close M1 or production rollout.

## Independent federation exit

M3 closes only when two reports come from distinct administrative organization
IDs, distinct federation keys, and separately managed TLS endpoints. Each
operator signs its own acceptance record and neither operator has access to the
other's signing seed. Container separation under one administrator remains
simulation regardless of technical equivalence.
