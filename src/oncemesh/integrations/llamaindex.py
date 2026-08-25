"""Optional LlamaIndex KV and ingestion-cache backend."""

from __future__ import annotations

from typing import Any

try:
    from llama_index.core.storage.kvstore.types import BaseKVStore, DEFAULT_COLLECTION
except ImportError as error:  # pragma: no cover - optional dependency
    raise ImportError(
        "LlamaIndex support requires: pip install 'oncemesh[llamaindex]'"
    ) from error

from ..execution_cache import ExecutionCacheBridge
from .base import RuntimeCacheAdapter
from .codecs import JsonValueCodec
from .index import ActiveKeyIndex, IndexedRuntimeCacheAdapter, MemoryActiveKeyIndex


LLAMAINDEX_SERIALIZER = "oncemesh.llamaindex-json/v1"


class OnceMeshLlamaIndexKVStore(BaseKVStore):
    def __init__(
        self,
        bridge: ExecutionCacheBridge,
        *,
        index: ActiveKeyIndex | None = None,
        ttl: int | None = None,
    ) -> None:
        if bridge.runtime != "llamaindex":
            raise ValueError("LlamaIndex adapter requires a 'llamaindex' runtime bridge")
        adapter: RuntimeCacheAdapter[dict[str, Any]] = RuntimeCacheAdapter(
            bridge, JsonValueCodec(LLAMAINDEX_SERIALIZER)
        )
        self.cache = IndexedRuntimeCacheAdapter(adapter, index or MemoryActiveKeyIndex())
        self.ttl = ttl

    @staticmethod
    def _namespace(collection: str) -> tuple[str, ...]:
        if not isinstance(collection, str) or not collection:
            raise ValueError("collection must be a non-empty string")
        return ("llamaindex", collection)

    def put(self, key: str, val: dict, collection: str = DEFAULT_COLLECTION) -> None:
        if not isinstance(val, dict):
            raise ValueError("LlamaIndex cache values must be dictionaries")
        self.cache.put(self._namespace(collection), key, val, ttl=self.ttl)

    async def aput(self, key: str, val: dict, collection: str = DEFAULT_COLLECTION) -> None:
        if not isinstance(val, dict):
            raise ValueError("LlamaIndex cache values must be dictionaries")
        await self.cache.aput(self._namespace(collection), key, val, ttl=self.ttl)

    def put_all(
        self,
        kv_pairs: list[tuple[str, dict]],
        collection: str = DEFAULT_COLLECTION,
        batch_size: int = 1,
    ) -> None:
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        for key, value in kv_pairs:
            self.put(key, value, collection)

    async def aput_all(
        self,
        kv_pairs: list[tuple[str, dict]],
        collection: str = DEFAULT_COLLECTION,
        batch_size: int = 1,
    ) -> None:
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        for key, value in kv_pairs:
            await self.aput(key, value, collection)

    def get(self, key: str, collection: str = DEFAULT_COLLECTION) -> dict | None:
        value = self.cache.get(self._namespace(collection), key)
        return value.copy() if isinstance(value, dict) else None

    async def aget(self, key: str, collection: str = DEFAULT_COLLECTION) -> dict | None:
        value = await self.cache.aget(self._namespace(collection), key)
        return value.copy() if isinstance(value, dict) else None

    def get_all(self, collection: str = DEFAULT_COLLECTION) -> dict[str, dict]:
        return {
            key: value.copy()
            for key, value in self.cache.get_all(self._namespace(collection)).items()
        }

    async def aget_all(self, collection: str = DEFAULT_COLLECTION) -> dict[str, dict]:
        return {
            key: value.copy()
            for key, value in (await self.cache.aget_all(self._namespace(collection))).items()
        }

    def delete(self, key: str, collection: str = DEFAULT_COLLECTION) -> bool:
        return self.cache.delete(self._namespace(collection), key)

    async def adelete(self, key: str, collection: str = DEFAULT_COLLECTION) -> bool:
        return await self.cache.adelete(self._namespace(collection), key)

    def clear(self, collection: str | None = None) -> int:
        return self.cache.clear(None if collection is None else self._namespace(collection))

    async def aclear(self, collection: str | None = None) -> int:
        return await self.cache.aclear(
            None if collection is None else self._namespace(collection)
        )
