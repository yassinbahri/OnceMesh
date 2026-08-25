# 0023 — Filesystem lock is the local transaction boundary

Status: accepted

The active-key index, not immutable object storage, defines visibility for
mutable runtime keys. A path-scoped operating-system lock spans generation
selection, immutable publication, and atomic index replacement. This preserves
the last committed value through exceptions and process crashes without adding
a second object format or a recovery journal.

The tradeoff is that a crash can leave an unreachable immutable object. That is
safe and collectible. Holding the index lock during filesystem publication also
reduces same-index write concurrency; separate indexes remain independent.
Distributed coordination and network-filesystem lock behavior are outside this
local reference profile.
