"""Minimal template for an exact-key third-party OnceMesh adapter.

Replace ``WidgetRuntimeCache`` and its three native methods with the host
framework's interface. Keep identity, storage, policy, and freshness in the
shared bridge.
"""

from __future__ import annotations

from typing import Any

from oncemesh import (
    ExecutionCacheBridge,
    ExecutionCacheKey,
    MemoryStore,
    derive_authorization_partition,
)
from oncemesh.integrations import JsonValueCodec, RuntimeCacheAdapter


WIDGET_SERIALIZER = "example.widget-json/v1"


class WidgetRuntimeCache:
    """Example translation layer; it contains no OnceMesh policy logic."""

    def __init__(self, bridge: ExecutionCacheBridge, *, ttl: int | None = 300) -> None:
        if bridge.runtime != "widget-runtime":
            raise ValueError("Widget adapter requires a 'widget-runtime' bridge")
        self._cache: RuntimeCacheAdapter[Any] = RuntimeCacheAdapter(
            bridge, JsonValueCodec(WIDGET_SERIALIZER)
        )
        self._ttl = ttl

    @staticmethod
    def _key(workflow: str, exact_native_key: str) -> ExecutionCacheKey:
        return ExecutionCacheKey(("widget", workflow), exact_native_key)

    def lookup(self, workflow: str, exact_native_key: str) -> Any | None:
        key = self._key(workflow, exact_native_key)
        return self._cache.get((key,)).get(key)

    def update(self, workflow: str, exact_native_key: str, value: Any) -> None:
        self._cache.set({self._key(workflow, exact_native_key): (value, self._ttl)})

    def clear(self, workflow: str) -> None:
        self._cache.clear((("widget", workflow),))


def main() -> None:
    """Run the template with core-only in-memory dependencies."""
    store = MemoryStore("widget-example")
    bridge = ExecutionCacheBridge(
        runtime="widget-runtime",
        serializer=WIDGET_SERIALIZER,
        authorization_partition=derive_authorization_partition(
            "example-tenant",
            ["example:local"],
            b"example-only-partition-key-32-bytes!!",
        ),
        stores=[store],
        publish_to=store,
        producer="widget-example",
    )
    cache = WidgetRuntimeCache(bridge)
    cache.update("demo", "sha256:exact-input", {"answer": 42})
    print(cache.lookup("demo", "sha256:exact-input"))


if __name__ == "__main__":
    main()
