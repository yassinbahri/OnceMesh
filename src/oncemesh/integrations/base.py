"""Shared codec and execution behavior for runtime-specific adapters."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from ..execution_cache import EncodedExecutionValue, ExecutionCacheBridge, ExecutionCacheKey


ValueT = TypeVar("ValueT")


class RuntimeValueCodec(Protocol[ValueT]):
    serializer_id: str

    def encode(self, value: ValueT) -> EncodedExecutionValue: ...

    def decode(self, value: EncodedExecutionValue) -> ValueT: ...


@dataclass(frozen=True)
class RuntimeCallOutcome(Generic[ValueT]):
    value: ValueT
    cache_hit: bool


class RuntimeCacheAdapter(Generic[ValueT]):
    """Framework-independent typed-value operations over the core bridge."""

    def __init__(self, bridge: ExecutionCacheBridge, codec: RuntimeValueCodec[ValueT]) -> None:
        if (
            not isinstance(codec.serializer_id, str)
            or not codec.serializer_id
            or codec.serializer_id != bridge.serializer
        ):
            raise ValueError("runtime codec identifier must match the bridge serializer")
        self.bridge = bridge
        self.codec = codec

    def get(self, keys: Iterable[ExecutionCacheKey]) -> dict[ExecutionCacheKey, ValueT]:
        values: dict[ExecutionCacheKey, ValueT] = {}
        for key, encoded in self.bridge.get(keys).items():
            try:
                values[key] = self.codec.decode(encoded)
            except Exception:
                continue
        return values

    async def aget(self, keys: Iterable[ExecutionCacheKey]) -> dict[ExecutionCacheKey, ValueT]:
        materialized = tuple(keys)
        return await asyncio.to_thread(self.get, materialized)

    def set(self, pairs: Mapping[ExecutionCacheKey, tuple[ValueT, int | None]]) -> None:
        encoded = {
            key: (self.codec.encode(value), ttl) for key, (value, ttl) in pairs.items()
        }
        self.bridge.set(encoded)

    async def aset(self, pairs: Mapping[ExecutionCacheKey, tuple[ValueT, int | None]]) -> None:
        await asyncio.to_thread(self.set, pairs)

    def get_or_execute(
        self,
        key: ExecutionCacheKey,
        execute: Callable[[], ValueT],
        *,
        ttl: int | None,
    ) -> RuntimeCallOutcome[ValueT]:
        cached = self.get((key,))
        if key in cached:
            return RuntimeCallOutcome(cached[key], True)
        value = execute()
        self.set({key: (value, ttl)})
        return RuntimeCallOutcome(value, False)

    async def aget_or_execute(
        self,
        key: ExecutionCacheKey,
        execute: Callable[[], Awaitable[ValueT]],
        *,
        ttl: int | None,
    ) -> RuntimeCallOutcome[ValueT]:
        cached = await self.aget((key,))
        if key in cached:
            return RuntimeCallOutcome(cached[key], True)
        value = await execute()
        await self.aset({key: (value, ttl)})
        return RuntimeCallOutcome(value, False)

    def clear(self, namespaces: Iterable[tuple[str, ...]] | None = None) -> None:
        self.bridge.clear(namespaces)

    async def aclear(self, namespaces: Iterable[tuple[str, ...]] | None = None) -> None:
        materialized = None if namespaces is None else tuple(namespaces)
        await asyncio.to_thread(self.clear, materialized)

    def set_enabled(self, enabled: bool) -> None:
        self.bridge.set_enabled(enabled)
