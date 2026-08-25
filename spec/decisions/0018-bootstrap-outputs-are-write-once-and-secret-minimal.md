# Decision 0018: Bootstrap outputs are write-once and secret-minimal

Status: accepted

## Context

Operator tooling handles the only private material in the federation pilot.
Convenient defaults such as printing seeds, overwriting key files, or silently
packaging artifacts would make accidental disclosure or publication likely.

## Decision

Never print private seeds. Require explicit new paths for private and public key
outputs, create them without replacement, and request owner-only file mode where
supported. Require two explicit public-classification confirmations before
publication packaging. Make preflight output public-data-only and network-free.

## Consequences

Bootstrap is slightly more deliberate and may require platform-specific ACL
work, especially on Windows. Re-running a command requires new paths, which
preserves prior keys and evidence rather than silently replacing them.
