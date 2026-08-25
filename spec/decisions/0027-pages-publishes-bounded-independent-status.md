# ADR 0027: Pages publishes bounded independent status

Status: accepted

## Context

The curated directory is readable by tools but difficult for people to explore.
Browser-side health checks would expose visitors to operator endpoints, produce
inconsistent cross-origin results, and make every visitor an uncontrolled probe.
Committing every status update would create noisy history and give an automated
monitor write authority over the reviewed registry.

## Decision

Publish a static GitHub Pages directory from a GitHub Actions artifact. The
workflow validates the registry, performs one bounded unauthenticated protocol
reachability check per active mesh, and places the resulting status snapshot in
the deployed artifact without committing it.

Keep registry status, recent reachability, and trust as three separate concepts.
The monitor has no federation credentials and never changes peer configuration.

## Consequences

- The initial service requires no separately hosted backend or database.
- Visitors never probe mesh operators directly.
- Status reflects one hosted runner location and one recent observation.
- GitHub Actions and Pages availability affect freshness but not the canonical
  registry.
- Historical analytics and multi-region monitoring remain future work.
