"""Optional LangChain LLM and chat-model cache adapter."""

from __future__ import annotations

from typing import Any
import warnings

try:
    from langchain_core.caches import BaseCache, RETURN_VAL_TYPE
    from langchain_core._api import LangChainBetaWarning
    from langchain_core.load import dumps, loads
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, Generation
except ImportError as error:  # pragma: no cover - optional dependency
    raise ImportError(
        "LangChain support requires: pip install 'oncemesh[langchain]'"
    ) from error

from ..canonical import canonical_json, digest_bytes
from ..execution_cache import EncodedExecutionValue, ExecutionCacheBridge, ExecutionCacheKey
from .base import RuntimeCacheAdapter


LANGCHAIN_SERIALIZER = "oncemesh.langchain-generations-json/v1"


class _LangChainGenerationCodec:
    serializer_id = LANGCHAIN_SERIALIZER

    def encode(self, value: RETURN_VAL_TYPE) -> EncodedExecutionValue:
        for generation in value:
            if type(generation) is Generation:
                continue
            if type(generation) is ChatGeneration and type(generation.message) is AIMessage:
                continue
            raise ValueError("LangChain cache profile supports Generation and AI ChatGeneration only")
        payload = dumps(list(value), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return EncodedExecutionValue("json", payload)

    def decode(self, value: EncodedExecutionValue) -> RETURN_VAL_TYPE:
        if value.type_tag != "json":
            raise ValueError("LangChain cache value has the wrong type tag")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", LangChainBetaWarning)
            decoded = loads(
                value.payload.decode("utf-8"),
                allowed_objects=[Generation, ChatGeneration, AIMessage],
                secrets_from_env=False,
            )
        if not isinstance(decoded, list) or any(
            type(item) not in (Generation, ChatGeneration) for item in decoded
        ):
            raise ValueError("LangChain cache value is not a generation list")
        return decoded


class OnceMeshLangChainCache(BaseCache):
    def __init__(self, bridge: ExecutionCacheBridge, *, ttl: int | None = None) -> None:
        if bridge.runtime != "langchain":
            raise ValueError("LangChain adapter requires a 'langchain' runtime bridge")
        self.adapter: RuntimeCacheAdapter[RETURN_VAL_TYPE] = RuntimeCacheAdapter(
            bridge, _LangChainGenerationCodec()
        )
        self.ttl = ttl

    @staticmethod
    def _key(prompt: str, llm_string: str) -> ExecutionCacheKey:
        if not isinstance(prompt, str) or not isinstance(llm_string, str):
            raise ValueError("prompt and llm_string must be strings")
        exact = digest_bytes(canonical_json({"prompt": prompt, "llm_string": llm_string}))
        return ExecutionCacheKey(("langchain", "llm"), exact)

    def lookup(self, prompt: str, llm_string: str) -> RETURN_VAL_TYPE | None:
        key = self._key(prompt, llm_string)
        return self.adapter.get((key,)).get(key)

    def update(self, prompt: str, llm_string: str, return_val: RETURN_VAL_TYPE) -> None:
        self.adapter.set({self._key(prompt, llm_string): (return_val, self.ttl)})

    def clear(self, **kwargs: Any) -> None:
        if kwargs:
            raise ValueError("OnceMesh LangChain clear does not accept filters")
        self.adapter.clear((("langchain", "llm"),))

    async def alookup(self, prompt: str, llm_string: str) -> RETURN_VAL_TYPE | None:
        key = self._key(prompt, llm_string)
        return (await self.adapter.aget((key,))).get(key)

    async def aupdate(
        self, prompt: str, llm_string: str, return_val: RETURN_VAL_TYPE
    ) -> None:
        await self.adapter.aset({self._key(prompt, llm_string): (return_val, self.ttl)})

    async def aclear(self, **kwargs: Any) -> None:
        if kwargs:
            raise ValueError("OnceMesh LangChain clear does not accept filters")
        await self.adapter.aclear((("langchain", "llm"),))
