# SQLite/WAL active-index stress analysis — 2026-08-25

M8 passed natively on Windows and in a non-root Linux container. Each platform
completed 20,000 SQLite operations, plus an identical 4,000-operation JSON
baseline, exact generation checks, live WAL-reader behavior, forced process
exit, reopen, and full SQLite integrity verification.

## Results

| Platform | JSON 4,000 commits | SQLite 4,000 commits | Speedup | SQLite 16,000 mixed |
|---|---:|---:|---:|---:|
| Windows / Python 3.12.13 | 101.960 s | 27.149 s | 3.756× | 44.099 s |
| Linux container / Python 3.12.14 | 38.082 s | 6.234 s | 6.109× | 9.006 s |

Both hot-key runs ended at the exact generation 3999. Both mixed runs completed
across 16 processes with `PRAGMA integrity_check = ok`. Readers observed the
previous committed revision while a writer held `BEGIN IMMEDIATE`; measured read
latency was 11.6 ms on Windows and 0.75 ms on Linux.

A child process on each platform exited with code 73 after immutable publication
but before SQLite commit. WAL recovery retained the prior revision and value,
the uncommitted publication ID remained unreachable, a following write
succeeded, and integrity remained `ok`.

## Synchronization profile finding

The initial Linux trial with WAL `synchronous=FULL` was only 0.722× the JSON
baseline. That result was rejected. The implemented high-throughput default is
WAL `NORMAL`, which preserves atomicity, consistency, and process-crash recovery.
Applications requiring the newest commit to survive operating-system or power
failure can explicitly select `synchronous="FULL"`; the test suite verifies that
both profiles are accepted and invalid profiles fail closed.

## Functionality and regression evidence

- Explicit JSON-to-SQLite migration preserves the source and refuses an occupied
  destination unless `replace=True` is supplied.
- Reopen, overwrite, delete, clear, sync/async indexed behavior, publication
  rollback, bounded busy timeout, WAL mode, schema version, and legacy JSON
  migration passed.
- Python with all framework dependencies: 171 tests passed.
- Dependency-light Python: 171 tests passed with 9 expected optional skips.
- Real adapter platform: 9 checks passed across Python, LangGraph 1.2.11,
  LangChain Core 1.6.0, and LlamaIndex Core 0.14.24.
- Runtime SDK evaluation: 6 checks passed; both contributor examples ran.
- Independent Node.js conformance: 29 checks passed.
- Isolated Docker federation regression: 20 checks passed with zero secret-scan
  matches.

Machine-readable reports: `sqlite-index-stress-20260824.json` and
`sqlite-index-stress-linux-20260824.json`.
