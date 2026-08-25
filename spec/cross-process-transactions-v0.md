# Cross-process index transactions v0

Status: implemented reference contract

## Purpose

OnceMesh result objects are immutable, while runtime adapters may need mutable
key enumeration, deletion, overwrite, and clear behavior. This contract defines
the local-filesystem coordination boundary that keeps those mutable decisions
correct when several processes share one store.

## Locking contract

- Each mutable JSON state file has a sibling `<state-file>.lock` file.
- Every read and every read-modify-replace operation holds an exclusive
  operating-system advisory lock on that file.
- A process first obtains the path-scoped in-process lock and then the operating
  system lock. Implementations must not reverse that order.
- Acquisition has a finite configurable timeout and raises a distinct timeout
  error. A process exit releases the operating-system lock; the harmless lock
  file may remain.
- JSON state is published through a completed, flushed temporary file followed
  by same-filesystem atomic replacement.

The reference implementation uses byte-range locking on Windows and `flock` on
POSIX. It claims local filesystem semantics only. Network filesystems must be
qualified independently before sharing mutable state.

## Publication transaction

An indexed put is one visibility transaction:

1. lock the active-key index;
2. read the last committed generation and active bit;
3. select the next generation and a fresh opaque publication ID without
   modifying the index;
4. publish the immutable value under an identity containing both values;
5. atomically replace the index with that generation and publication ID active;
6. release the lock.

If encoding or publication fails, the index is unchanged. If the process is
killed after immutable publication but before the index replacement, the prior
active value remains visible. The new immutable object is an unreachable orphan:
its publication ID is absent from the index and is never reused. It may be
reclaimed by a future garbage collector. This contract guarantees atomic
visibility, not atomic deletion of append-only objects.

Delete and clear atomically advance generations and deactivate keys. Indexed
clear does not rotate the execution bridge epoch: generation invalidation is its
single source of truth and therefore works across independently constructed
processes.

## Required safety behavior

- concurrent overwrites of one active key serialize and each commit advances its
  generation exactly once;
- a failed or killed publisher never hides or replaces the previous value;
- delete, clear, and re-add never resurrect an older immutable value;
- readers never parse partial epoch or index JSON;
- lost updates are forbidden for epoch rotation and index mutation;
- lock timeout and post-crash lock recovery are observable and testable;
- disabled or non-positive-TTL puts do not activate an index entry.

## Stress acceptance profile

The reference evidence must include multiple spawned processes, at least 10,000
mixed operations, same-key contention, independent epoch rotations with an exact
final count, forced process exit inside the publication transaction, reopen and
integrity checks, all adapter contracts, and the full Python, Node, and Docker
regression suites. Timing is recorded for comparison but is not a portable pass
criterion.
