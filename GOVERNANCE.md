# Governance

OnceMesh is specification-led. Repository maintainers are the people with merge
authority on the protected default branch. Their role is to preserve protocol
clarity, compatibility, safety boundaries, and independently reproducible
evidence—not to turn implementation accidents into standards.

Protocol-visible changes require a specification or ADR, accepted and rejected
examples, schema/conformance updates where applicable, and passing automated
checks. Maintainers seek consensus; when consensus is unavailable, the narrowest
safe behavior remains in place and the unresolved choice is documented.

Releases require review by a maintainer who did not author the release commit
when the project has at least two active maintainers. Publishing authority,
branch protection, and package-registry access should use least privilege and
must not depend on shared long-lived tokens.

No maintainer may relabel simulated evidence as a real organization or
independent-operator result. Conflicts of interest affecting an acceptance or
security decision must be disclosed and the affected maintainer must recuse.
