# Authoring an adapter

This guide is the shortest safe path from a framework cache interface to a
reviewable OnceMesh adapter.

## 1. Choose the adapter shape

Use `RuntimeCacheAdapter` when the framework supplies exact keys and needs
lookup, publication, TTL, and clear. LangGraph and LangChain use this shape.

Use `IndexedRuntimeCacheAdapter` when the framework also requires active-key
enumeration or per-key deletion. LlamaIndex uses this shape. Do not implement a
second mutable index in the framework module.

Use `MemoryActiveKeyIndex` for ephemeral single-process cases,
`FilesystemActiveKeyIndex` for a transparent low-volume reference, or
`SQLiteActiveKeyIndex` for contended local use. This choice belongs in
application wiring, not the framework adapter.

## 2. Define identity explicitly

Choose a stable runtime name and serializer identifier. Preserve every native
field capable of changing the output. If several native fields form the key,
hash their canonical structured object; never concatenate with an ambiguous
delimiter.

The application supplies an authorization partition and private stores when it
builds `ExecutionCacheBridge`. The adapter must not invent a tenant identity or
enable federation.

When one cached result is used to build another, include the upstream artifact
digest in the derived action identity and publish result v1 with the exact
upstream result-manifest digest. The first preserves computation identity; the
second lets lookup propagate freshness, trust, integrity, and explicit
invalidation. Never substitute one for the other.

Adapters for live sources must define a bounded TTL or an authoritative
validation method. A URL or request digest alone does not make mutable remote
state fresh. If no reliable freshness rule exists, keep the operation in shadow
mode or disable substitution. See
[`Mutable external state is an adapter obligation`](../user-guide.md#mutable-external-state-is-an-adapter-obligation)
for safe revision, validator, deployment, environment, and DNS patterns.

## 3. Reuse or implement a codec

Use `JsonValueCodec` for ordinary JSON values. A custom codec implements only:

```python
class MyCodec:
    serializer_id = "my-project.framework-value/v1"

    def encode(self, value): ...
    def decode(self, encoded): ...
```

The serializer identifier is part of action identity. Change it whenever wire
compatibility changes. Pickle and `repr` are not acceptable portable codecs.

## 4. Keep the framework module thin

The adapter should translate native method names, key shapes, values, batches,
and TTLs, then delegate. It should not call `Store`, `publish_result`, or `reuse`
directly. It should not reproduce expiry, digest, trust, partition, clear, or
disable checks.

Start from [`examples/custom_runtime_adapter.py`](../../examples/custom_runtime_adapter.py)
for exact caches or
[`examples/custom_indexed_adapter.py`](../../examples/custom_indexed_adapter.py)
for enumeration and deletion.

## 5. Register without importing the framework

Add an `AdapterDescriptor` in `integrations/registry.py`. Registry metadata must
remain importable with only OnceMesh core installed. Put framework imports
inside the adapter module's guarded import block and provide the exact install
extra in its error message.

An adapter maintained in another package can register without modifying
OnceMesh by exposing a descriptor factory as a Python entry point:

```toml
[project.entry-points."oncemesh.adapters"]
widget = "widget_oncemesh:adapter_descriptor"
```

Applications opt into loading installed third-party metadata with
`discover_adapters(include_plugins=True)`. Normal core imports never load those
packages.

## 6. Test at three levels

1. Run `probe_exact_adapter` or `probe_indexed_adapter` against the shared layer.
2. Test every native framework method, including async and clear/delete behavior.
3. Run at least one real framework workflow proving the adapter is actually used.

Also test malformed values, dependency absence, key variation, partition
isolation, failure non-publication, and compatibility imports when applicable.

## Pull-request checklist

- Specification and ADR precede implementation behavior.
- Optional dependency has a bounded version range and individual extra.
- Importing `oncemesh` does not import the framework.
- Serializer and runtime identifiers are stable and documented.
- Exact keys include all output-affecting inputs and configuration.
- Derived results identify upstream artifact bytes and attach exact result
  lineage when cascading admissibility is required.
- Generic runtime state cannot use a federation-import store.
- No storage, policy, codec, or index behavior is copied into the adapter.
- Shared probes, native contract tests, real workflow tests, and full regressions pass.
