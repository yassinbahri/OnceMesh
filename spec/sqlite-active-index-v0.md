# SQLite active-key index v0

Status: implemented reference contract

## Purpose

The SQLite active-key index is the high-contention local backend for
`ActiveKeyIndex`. It preserves the visibility and crash semantics of
`cross-process-transactions-v0.md` while avoiding whole-index JSON parsing and
replacement on every operation.

SQLite is part of the Python standard library; this backend adds no package or
framework dependency.

## Storage profile

- One SQLite database stores mutable active-key metadata only.
- The primary key is canonical namespace JSON plus the exact native key.
- Each row records generation, active state, and nullable publication ID.
- Schema version is recorded with `PRAGMA user_version`.
- The database uses WAL journal mode, a bounded configurable busy timeout, and a
  configurable `NORMAL` or `FULL` synchronous profile.
- `NORMAL` is the high-throughput default. It preserves atomicity, consistency,
  and application/process-crash recovery, but the newest commits may be lost
  after an operating-system crash or power loss.
- `FULL` is available when every committed index change must cross that stronger
  power-loss boundary, at the cost of additional synchronization latency.
- A fresh connection is used per public operation so processes and threads do
  not share connection state.

Immutable artifacts and result manifests remain in OnceMesh stores. They MUST
NOT be copied into SQLite.

## Transaction behavior

Mutations use `BEGIN IMMEDIATE`.

Transactional put reads the last committed row, selects the next generation and
a fresh publication ID, invokes immutable publication, writes the row, and
commits. Publication exceptions roll back the database transaction and retain
the previous row. Process exit before commit causes SQLite recovery to roll back
the writer; any immutable object already published remains unreachable because
its publication ID was never committed.

WAL readers may continue reading the last committed revision while one writer is
publishing. Writers serialize at SQLite's database write boundary. A bounded
`SQLITE_BUSY` or locked condition maps to `CoordinationTimeoutError`.

Publisher callbacks MUST NOT recursively mutate the same index. They may publish
to independent immutable stores.

## JSON index migration

Migration is explicit and separately invoked. It takes a locked snapshot of a
valid filesystem JSON index and imports it in one SQLite transaction.

- The default refuses a non-empty destination.
- Replacement requires an explicit `replace=True` argument.
- The source is never modified or deleted.
- Generations, active bits, and committed publication IDs are preserved.
- Legacy v1 JSON rows migrate with a null publication ID.

## Acceptance criteria

1. Shared indexed conformance passes for memory, JSON filesystem, and SQLite.
2. Reopen, overwrite, delete, clear, async adapter, and JSON migration pass.
3. Publication exceptions and forced process exit retain the last committed row.
4. At least 20,000 cross-process operations complete with exact epoch/generation
   invariants and `PRAGMA integrity_check = ok`.
5. Windows and non-root Linux container stress evidence is recorded.
6. SQLite materially improves the M7 mixed-workload timing on each tested
   platform without weakening any Python, Node, Docker, or framework regression.
