"""Optional LangGraph adapter for the shared integration platform."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

try:
    from langgraph.cache.base import BaseCache, FullKey, Namespace
    from langgraph.checkpoint.serde.base import SerializerProtocol
except ImportError as error:  # pragma: no cover - optional dependency
    raise ImportError(
        "LangGraph support requires: pip install 'oncemesh[langgraph]'"
    ) from error

from ..execution_cache import EncodedExecutionValue, ExecutionCacheBridge, ExecutionCacheKey
from .base import RuntimeCacheAdapter


class _LangGraphCodec:
    def __init__(self, serializer_id: str, serde: SerializerProtocol) -> None:
        self.serializer_id = serializer_id
        self.serde = serde

    def encode(self, value: Any) -> EncodedExecutionValue:
        type_tag, payload = self.serde.dumps_typed(value)
        return EncodedExecutionValue(type_tag, payload)

    def decode(self, value: EncodedExecutionValue) -> Any:
        return self.serde.loads_typed((value.type_tag, value.payload))


class OnceMeshLangGraphCache(BaseCache[Any]):
    def __init__(
        self,
        bridge: ExecutionCacheBridge,
        *,
        serde: SerializerProtocol | None = None,
    ) -> None:
        if bridge.runtime != "langgraph":
            raise ValueError("LangGraph adapter requires a 'langgraph' runtime bridge")
        super().__init__(serde=serde)
        self.adapter: RuntimeCacheAdapter[Any] = RuntimeCacheAdapter(
            bridge, _LangGraphCodec(bridge.serializer, self.serde)
        )

    @staticmethod
    def _key(full_key: FullKey) -> ExecutionCacheKey:
        namespace, key = full_key
        return ExecutionCacheKey(tuple(namespace), key)

    def get(self, keys: Sequence[FullKey]) -> dict[FullKey, Any]:
        translated = {self._key(key): key for key in keys}
        return {
            translated[core_key]: value
            for core_key, value in self.adapter.get(translated).items()
        }

    async def aget(self, keys: Sequence[FullKey]) -> dict[FullKey, Any]:
        translated = {self._key(key): key for key in keys}
        return {
            translated[core_key]: value
            for core_key, value in (await self.adapter.aget(translated)).items()
        }

    def set(self, pairs: Mapping[FullKey, tuple[Any, int | None]]) -> None:
        self.adapter.set({self._key(full_key): pair for full_key, pair in pairs.items()})

    async def aset(self, pairs: Mapping[FullKey, tuple[Any, int | None]]) -> None:
        await self.adapter.aset(
            {self._key(full_key): pair for full_key, pair in pairs.items()}
        )

    def clear(self, namespaces: Sequence[Namespace] | None = None) -> None:
        self.adapter.clear(None if namespaces is None else (tuple(ns) for ns in namespaces))

    async def aclear(self, namespaces: Sequence[Namespace] | None = None) -> None:
        await self.adapter.aclear(
            None if namespaces is None else (tuple(ns) for ns in namespaces)
        )
