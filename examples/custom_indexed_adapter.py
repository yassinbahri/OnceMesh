"""Minimal template for a framework that needs enumerate and delete semantics."""

from __future__ import annotations

from typing import Any

from oncemesh import (
    ExecutionCacheBridge,
    MemoryActiveKeyIndex,
    MemoryStore,
    RuntimeCacheAdapter,
    derive_authorization_partition,
)
from oncemesh.integrations import IndexedRuntimeCacheAdapter, JsonValueCodec


WIDGET_KV_SERIALIZER = "example.widget-kv-json/v1"


class WidgetKVStore:
    def __init__(self, bridge: ExecutionCacheBridge) -> None:
        exact = RuntimeCacheAdapter(bridge, JsonValueCodec(WIDGET_KV_SERIALIZER))
        self._cache: IndexedRuntimeCacheAdapter[Any] = IndexedRuntimeCacheAdapter(
            exact, MemoryActiveKeyIndex()
        )

    @staticmethod
    def _namespace(collection: str) -> tuple[str, ...]:
        return ("widget-kv", collection)

    def put(self, collection: str, key: str, value: Any) -> None:
        self._cache.put(self._namespace(collection), key, value, ttl=300)

    def get(self, collection: str, key: str) -> Any | None:
        return self._cache.get(self._namespace(collection), key)

    def get_all(self, collection: str) -> dict[str, Any]:
        return self._cache.get_all(self._namespace(collection))

    def delete(self, collection: str, key: str) -> bool:
        return self._cache.delete(self._namespace(collection), key)


def main() -> None:
    store = MemoryStore("widget-kv-example")
    bridge = ExecutionCacheBridge(
        runtime="widget-kv",
        serializer=WIDGET_KV_SERIALIZER,
        authorization_partition=derive_authorization_partition(
            "example-tenant",
            ["example:local"],
            b"example-only-partition-key-32-bytes!!",
        ),
        stores=[store],
        publish_to=store,
        producer="widget-kv-example",
    )
    cache = WidgetKVStore(bridge)
    cache.put("demo", "key", {"version": 1})
    cache.put("demo", "key", {"version": 2})
    print(cache.get_all("demo"))
    cache.delete("demo", "key")
    print(cache.get("demo", "key"))


if __name__ == "__main__":
    main()
