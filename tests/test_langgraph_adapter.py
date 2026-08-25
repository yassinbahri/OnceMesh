from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import CachePolicy

    from oncemesh.langgraph import OnceMeshLangGraphCache
except ImportError:  # pragma: no cover - optional dependency
    StateGraph = None

from oncemesh import (  # noqa: E402
    ExecutionCacheBridge,
    MemoryStore,
    derive_authorization_partition,
)


@unittest.skipIf(StateGraph is None, "LangGraph optional dependency is not installed")
class LangGraphAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemoryStore("project")
        self.bridge = ExecutionCacheBridge(
            runtime="langgraph",
            serializer="langgraph.jsonplus/no-pickle-v1",
            authorization_partition=derive_authorization_partition(
                "tenant-a", ["project:agent"], b"l" * 32
            ),
            stores=[self.store],
            publish_to=self.store,
            producer="agent-runtime",
        )
        self.cache = OnceMeshLangGraphCache(self.bridge)

    def test_direct_sync_and_async_contract(self) -> None:
        key = (("graph", "node"), "exact")
        value = [{"answer": 42}, "metadata"]
        self.cache.set({key: (value, 60)})
        self.assertEqual(self.cache.get([key]), {key: value})

        async def exercise() -> None:
            other = (("graph", "async-node"), "exact")
            await self.cache.aset({other: (value, 60)})
            self.assertEqual(await self.cache.aget([other]), {other: value})
            await self.cache.aclear([other[0]])
            self.assertEqual(await self.cache.aget([other]), {})

        asyncio.run(exercise())

    def test_real_graph_reuses_exact_node_result(self) -> None:
        class State(TypedDict, total=False):
            number: int
            doubled: int

        calls = 0

        def expensive(state: State) -> dict[str, int]:
            nonlocal calls
            calls += 1
            return {"doubled": state["number"] * 2}

        builder = StateGraph(State)
        builder.add_node("expensive", expensive, cache_policy=CachePolicy(ttl=60))
        builder.add_edge(START, "expensive")
        builder.add_edge("expensive", END)
        graph = builder.compile(cache=self.cache)

        first = graph.invoke({"number": 21})
        second = graph.invoke({"number": 21})
        different = graph.invoke({"number": 22})

        self.assertEqual(first, {"number": 21, "doubled": 42})
        self.assertEqual(second, first)
        self.assertEqual(different, {"number": 22, "doubled": 44})
        self.assertEqual(calls, 2)

    def test_real_async_graph_reuses_exact_node_result(self) -> None:
        class State(TypedDict, total=False):
            text: str
            normalized: str

        calls = 0

        async def expensive(state: State) -> dict[str, str]:
            nonlocal calls
            calls += 1
            return {"normalized": state["text"].strip().lower()}

        builder = StateGraph(State)
        builder.add_node("expensive", expensive, cache_policy=CachePolicy(ttl=60))
        builder.add_edge(START, "expensive")
        builder.add_edge("expensive", END)
        graph = builder.compile(cache=self.cache)

        async def exercise() -> tuple[dict, dict]:
            return (
                await graph.ainvoke({"text": "  OnceMesh  "}),
                await graph.ainvoke({"text": "  OnceMesh  "}),
            )

        first, second = asyncio.run(exercise())
        self.assertEqual(first, {"text": "  OnceMesh  ", "normalized": "oncemesh"})
        self.assertEqual(second, first)
        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
