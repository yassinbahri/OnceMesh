"""Native Python JSON integration for custom agents and workflows."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from ..execution_cache import ExecutionCacheBridge, ExecutionCacheKey
from .base import RuntimeCacheAdapter, RuntimeCallOutcome
from .codecs import JsonValueCodec


PYTHON_JSON_SERIALIZER = "oncemesh.python-json/v1"


class PythonJsonCodec(JsonValueCodec):
    serializer_id = PYTHON_JSON_SERIALIZER

    def __init__(self) -> None:
        super().__init__(self.serializer_id)


class OnceMeshPythonCache:
    """Explicit exact-key cache for custom Python agents and workflows."""

    def __init__(self, bridge: ExecutionCacheBridge) -> None:
        if bridge.runtime != "python":
            raise ValueError("Python adapter requires a 'python' runtime bridge")
        self.adapter: RuntimeCacheAdapter[Any] = RuntimeCacheAdapter(bridge, PythonJsonCodec())

    @staticmethod
    def key(namespace: Iterable[str], exact_key: str) -> ExecutionCacheKey:
        return ExecutionCacheKey(tuple(namespace), exact_key)

    def invoke(
        self,
        namespace: Iterable[str],
        exact_key: str,
        execute: Callable[[], Any],
        *,
        ttl: int | None,
    ) -> RuntimeCallOutcome[Any]:
        return self.adapter.get_or_execute(self.key(namespace, exact_key), execute, ttl=ttl)

    async def ainvoke(
        self,
        namespace: Iterable[str],
        exact_key: str,
        execute: Callable[[], Awaitable[Any]],
        *,
        ttl: int | None,
    ) -> RuntimeCallOutcome[Any]:
        return await self.adapter.aget_or_execute(
            self.key(namespace, exact_key), execute, ttl=ttl
        )

    def clear(self, namespaces: Iterable[tuple[str, ...]] | None = None) -> None:
        self.adapter.clear(namespaces)

    async def aclear(self, namespaces: Iterable[tuple[str, ...]] | None = None) -> None:
        await self.adapter.aclear(namespaces)

    def set_enabled(self, enabled: bool) -> None:
        self.adapter.set_enabled(enabled)
