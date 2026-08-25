from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    from langchain_core.globals import set_llm_cache
    from langchain_core.language_models.fake import FakeListLLM
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, Generation
    from oncemesh.integrations.langchain import (
        LANGCHAIN_SERIALIZER,
        OnceMeshLangChainCache,
    )
except ImportError:  # pragma: no cover - optional dependency
    OnceMeshLangChainCache = None

from oncemesh import ExecutionCacheBridge, MemoryStore, derive_authorization_partition  # noqa: E402


@unittest.skipIf(OnceMeshLangChainCache is None, "LangChain optional dependency is not installed")
class LangChainAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemoryStore("langchain")
        bridge = ExecutionCacheBridge(
            runtime="langchain",
            serializer=LANGCHAIN_SERIALIZER,
            authorization_partition=derive_authorization_partition(
                "tenant-a", ["project:langchain"], b"c" * 32
            ),
            stores=[self.store],
            publish_to=self.store,
            producer="langchain-runtime",
        )
        self.cache = OnceMeshLangChainCache(bridge, ttl=60)

    def tearDown(self) -> None:
        set_llm_cache(None)

    def test_generation_and_chat_generation_round_trip(self) -> None:
        values = [
            Generation(text="Paris", generation_info={"finish_reason": "stop"}),
            ChatGeneration(message=AIMessage(content="Hello")),
        ]
        self.cache.update("prompt", "model=config", values)
        result = self.cache.lookup("prompt", "model=config")
        self.assertEqual(result, values)
        self.assertIsNone(self.cache.lookup("other", "model=config"))

    def test_async_contract_and_clear(self) -> None:
        async def exercise() -> None:
            await self.cache.aupdate("prompt", "model=config", [Generation(text="cached")])
            self.assertEqual(
                await self.cache.alookup("prompt", "model=config"),
                [Generation(text="cached")],
            )
            await self.cache.aclear()
            self.assertIsNone(await self.cache.alookup("prompt", "model=config"))

        asyncio.run(exercise())

    def test_real_fake_llm_uses_cache(self) -> None:
        set_llm_cache(self.cache)
        model = FakeListLLM(responses=["first", "second"], cache=True)
        self.assertEqual(model.invoke("same"), "first")
        self.assertEqual(model.invoke("same"), "first")
        self.assertEqual(model.invoke("different"), "second")


if __name__ == "__main__":
    unittest.main()
