# Decision 0019: Sandbox evidence is high-fidelity but never independent

Status: accepted

## Context

Containers can separate users, filesystems, secrets, and networks well enough to
exercise the federation trust boundaries. The host operator nevertheless holds
ultimate authority over every sandbox component.

## Decision

Build a three-role container rehearsal with separate secret mounts and a private
network. Exercise the same commands and manifests intended for external use.
Label every aggregate result as simulated and explicitly set administrative
independence to false.

## Consequences

The project gains reproducible acceptance coverage without making a false claim
about organizational governance or key custody. Real M3 completion still
requires evidence signed off by two external administrative owners.
