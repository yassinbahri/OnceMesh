# Adapter transaction extreme-stress analysis — 2026-08-24

The cross-process transactional durability profile passed natively on Windows
with Python 3.12.13 and inside a non-root Linux container with Python 3.12.14.
Each platform completed 11,600 coordinated operations across 28 spawned workers,
for 23,200 operations total, then passed explicit crash and timeout recovery
probes.

## Results

- Eight epoch writers performed 800 global and 800 namespace rotations. The
  reopened registry reported exactly `(800, 800)` with no lost update.
- Eight writers committed 1,000 overwrites of one hot key. The final committed
  generation was exactly 999 and its value decoded successfully.
- Twelve workers performed 9,000 mixed put, get, delete, and namespace-clear
  operations over 128 keys. Reopen succeeded and all 1,785 JSON state and
  immutable manifest files parsed; no temporary publication file survived.
- A writer was forced to exit with code 73 after immutable publication but before
  index commit. The prior revision and value remained active. A following write
  succeeded, and the abandoned publication stayed unreachable because it had a
  distinct uncommitted publication ID.
- A contended lock produced the required bounded timeout, then was acquired after
  the owning process exited.

## Regression evidence

- Python with all real adapter dependencies: 165 tests passed.
- Dependency-light Python environment: 165 tests passed, 9 optional framework
  tests skipped as designed.
- Real adapter evaluation: Python, LangGraph 1.2.11, LangChain Core 1.6.0, and
  LlamaIndex Core 0.14.24 passed all 8 platform checks.
- Runtime SDK evaluation passed all 6 checks.
- Independent Node.js v22.20.0 conformance passed 29 checks.
- Docker Desktop Linux three-role federation acceptance passed 20 checks,
  including internal TLS, non-root/read-only isolation, withdrawal, real lease
  expiry, untrusted-peer denial, and a zero-match secret scan.

## Performance interpretation

Safety passed, but the reference filesystem index is intentionally conservative.
On Windows, the 9,000-operation mixed phase took 224.954 worker seconds and
247.851 seconds including full reopen and integrity scanning. The equivalent
Linux container phase took 22.419 and 22.628 seconds respectively. A single JSON index, per-operation
file-lock acquisition, whole-index replacement, and durable immutable publication
make it suitable as a correctness reference and modest local deployment—not as a
high-throughput shared production index. A SQLite/WAL or service-backed index can
implement the same `ActiveKeyIndex` transaction contract without changing
framework adapters.

Machine-readable evidence: `adapter-stress-20260824.json` and
`adapter-stress-linux-20260824.json`.
