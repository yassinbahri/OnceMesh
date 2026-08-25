# Adapter platform v0

Status: implemented reference profile for M6.

## Goals

OnceMesh integrations MUST be understandable, independently installable, and
small enough for external contributors to review. Shared behavior belongs in
one reusable layer rather than being copied into framework modules.

The platform supports two adapter shapes:

- exact execution adapters for runtimes that provide exact keys and optional
  TTLs; and
- indexed key-value adapters for runtimes that additionally require active-key
  enumeration and per-key deletion.

## Package layout

Canonical integration code lives under `oncemesh.integrations`:

```text
integrations/
  base.py          shared typed runtime adapter
  codecs.py        reusable safe codecs
  index.py         mutable active-key indexes and indexed adapter
  registry.py      dependency-free adapter metadata
  python.py        native Python facade
  langgraph.py     optional LangGraph adapter
  langchain.py     optional LangChain LLM cache adapter
  llamaindex.py    optional LlamaIndex KV/ingestion cache adapter
```

Legacy import modules remain compatibility shims for the v0 development line.
They MUST contain no independent behavior.

## Dependency rule

Importing `oncemesh` or `oncemesh.integrations` MUST NOT import optional
framework packages. Each optional adapter imports its framework only inside its
own module and raises one actionable installation error when unavailable.

The registry exposes adapter name, purpose, import path, class name, optional
dependency extra, maturity, and capabilities without importing the adapter.

## Reuse rule

An integration module MAY translate native keys, values, batches, TTLs, and
method names. It MUST delegate:

- typed encoding/decoding to a codec;
- exact lookup and publication to `RuntimeCacheAdapter`;
- mutable enumeration and deletion to `IndexedRuntimeCacheAdapter`; and
- identity, trust, partitioning, freshness, immutable storage, integrity, and
  disable behavior to `ExecutionCacheBridge`.

Framework modules MUST NOT call result stores directly or duplicate those
checks.

## Active-key index

The active-key index is mutable metadata layered over immutable OnceMesh
objects. For each `(namespace, native_key)` it records a non-negative generation,
an active bit, and—when transactionally published—an opaque publication ID.

- First activation uses generation zero.
- Delete increments the generation and marks the key inactive.
- Re-activation retains that incremented generation, preventing resurrection of
  an older immutable result.
- Namespace clear increments the generation of every known active key and marks
  them inactive.
- Enumeration returns active native keys only.

The indexed adapter hashes the canonical native key, generation, and publication
ID into the exact core key. Raw mutable keys need not appear in action manifests.
Memory and atomic filesystem reference indexes are provided. The filesystem v1
profile uses operating-system locks for cross-process coordination and reads the
legacy v0 index format.

`SQLiteActiveKeyIndex` implements the same interface as the recommended
high-contention local tier. Framework modules MUST accept the interface rather
than depending on one backend.

Publication and index activation follow `cross-process-transactions-v0.md`. A
crash may create an unreachable immutable object, but its unique publication ID
prevents that orphan from becoming visible during a later generation retry.

## Built-in adapter profiles

- Native Python: explicit exact keys and safe JSON values.
- LangGraph: `BaseCache` full-key batches and per-entry TTL.
- LangChain: LLM `BaseCache` prompt plus complete `llm_string`, with configurable
  local TTL.
- LlamaIndex: `BaseKVStore` collections, get-all, delete, sync, and async methods
  backed by the active-key index.

Generic framework values remain private and MUST NOT use federation-import
stores.

## Contributor contract

A new adapter contribution MUST include:

1. one dependency-free registry descriptor;
2. one optional module containing only native translation;
3. an extra in `pyproject.toml` with bounded dependency versions;
4. direct contract tests and at least one real-framework test;
5. the shared safety tests appropriate to exact or indexed behavior; and
6. user documentation based on the provided template.

Adapters MUST use explicit stable serializer identifiers and exact keys. They
MUST NOT use pickle, `repr`, Python object identity, semantic similarity, or
implicit public federation as a default identity or serialization mechanism.

## Acceptance criteria

1. Existing Python and LangGraph imports remain compatible.
2. Four integrations are discoverable without loading optional dependencies.
3. Native Python, LangGraph, LangChain, and LlamaIndex pass real API tests.
4. Filesystem index reopen preserves active keys and deletion generations.
5. Delete followed by re-put cannot resurrect the older value.
6. Framework modules contain translation only and share codecs/index behavior.
7. A documented adapter template can be copied without copying policy logic.
8. Full Python, Node, and Docker regressions pass.
