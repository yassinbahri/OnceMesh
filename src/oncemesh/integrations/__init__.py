"""Dependency-light building blocks and discovery for OnceMesh integrations."""

from .base import RuntimeCacheAdapter, RuntimeCallOutcome, RuntimeValueCodec
from .codecs import JsonValueCodec
from .index import (
    ActiveKeyIndex,
    FilesystemActiveKeyIndex,
    IndexedRuntimeCacheAdapter,
    MemoryActiveKeyIndex,
    SQLiteActiveKeyIndex,
)
from .registry import (
    AdapterDescriptor,
    builtin_adapters,
    discover_adapters,
    get_adapter,
    load_adapter_class,
)
from .conformance import (
    AdapterConformanceCheck,
    AdapterConformanceReport,
    probe_exact_adapter,
    probe_indexed_adapter,
)

__all__ = [
    "ActiveKeyIndex",
    "AdapterDescriptor",
    "FilesystemActiveKeyIndex",
    "IndexedRuntimeCacheAdapter",
    "JsonValueCodec",
    "MemoryActiveKeyIndex",
    "SQLiteActiveKeyIndex",
    "RuntimeCacheAdapter",
    "RuntimeCallOutcome",
    "RuntimeValueCodec",
    "builtin_adapters",
    "get_adapter",
    "discover_adapters",
    "load_adapter_class",
    "AdapterConformanceCheck",
    "AdapterConformanceReport",
    "probe_exact_adapter",
    "probe_indexed_adapter",
]
