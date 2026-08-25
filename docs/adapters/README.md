# OnceMesh adapters

Adapters connect a framework's native cache interface to the same OnceMesh
execution-cache bridge. They are deliberately thin: adapters translate; the
bridge decides whether reuse is safe.

## Built-in adapters

| Adapter | Install extra | Native contract | Capabilities |
|---|---|---|---|
| Python | core | explicit callable | sync, async, TTL, JSON |
| LangGraph | `langgraph` | `BaseCache` | batches, per-entry TTL, clear |
| LangChain | `langchain` | LLM `BaseCache` | LLM/chat generations, async, clear |
| LlamaIndex | `llamaindex` | `BaseKVStore` | collections, enumerate, delete, async |

Install only what an application uses:

```bash
python -m pip install -e ".[llamaindex]"
```

Or install every built-in adapter for development:

```bash
python -m pip install -e ".[adapters]"
```

The dependency-free registry can drive documentation or setup UIs without
loading those frameworks:

```python
from oncemesh.integrations import builtin_adapters

for adapter in builtin_adapters():
    print(adapter.name, adapter.extra, adapter.capabilities)
```

## Where code belongs

- Framework-independent typed lookup: `integrations/base.py`
- Safe reusable codecs: `integrations/codecs.py`
- Enumeration and deletion: `integrations/index.py`
- Framework translation: one optional module named after the framework
- Public metadata: `integrations/registry.py`
- Reusable CI probes: `integrations/conformance.py`

Framework modules must not access OnceMesh stores directly. This keeps trust,
freshness, integrity, partition, disable, and federation behavior identical
across every adapter.

## Choosing an active-key index

Indexed adapters accept the shared `ActiveKeyIndex` interface:

- `MemoryActiveKeyIndex` is for one-process tests and ephemeral applications.
- `FilesystemActiveKeyIndex` is a transparent JSON correctness reference for
  modest local workloads.
- `SQLiteActiveKeyIndex` is the recommended local backend when threads or
  processes contend. It uses WAL and has no third-party dependency.

SQLite defaults to `synchronous="NORMAL"`, which preserves consistency and
process-crash recovery. Select `synchronous="FULL"` when the newest committed
index update must also survive an operating-system crash or power loss.

Migration is explicit and keeps the source JSON file:

```python
from oncemesh import FilesystemActiveKeyIndex, SQLiteActiveKeyIndex

source = FilesystemActiveKeyIndex("active-keys.json")
destination = SQLiteActiveKeyIndex("active-keys.sqlite3")
destination.import_filesystem(source)
```

The destination must be empty unless the caller deliberately supplies
`replace=True`.

See [Authoring an adapter](authoring.md) for the contribution workflow.
The [adapter catalog](catalog.md) records implemented integrations and the
expansion queue without presenting planned work as current support.
