from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncemesh import (  # noqa: E402
    EncodedExecutionValue,
    ExecutionCacheBridge,
    ExecutionCacheKey,
    MemoryStore,
    OnceMeshPythonCache,
    PYTHON_JSON_SERIALIZER,
    PythonJsonCodec,
    RuntimeCacheAdapter,
    derive_authorization_partition,
)


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 24, 16, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


class RuntimeAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemoryStore("project")
        self.clock = MutableClock()
        self.partition = derive_authorization_partition(
            "tenant-a", ["project:python"], b"r" * 32
        )
        self.bridge = ExecutionCacheBridge(
            runtime="python",
            serializer=PYTHON_JSON_SERIALIZER,
            authorization_partition=self.partition,
            stores=[self.store],
            publish_to=self.store,
            producer="python-runtime",
            clock=self.clock,
        )
        self.cache = OnceMeshPythonCache(self.bridge)

    def test_sync_callable_executes_once_and_reports_hit(self) -> None:
        calls = 0

        def execute() -> dict:
            nonlocal calls
            calls += 1
            return {"answer": 42, "score": 0.5}

        first = self.cache.invoke(("workflow", "step"), "exact", execute, ttl=60)
        second = self.cache.invoke(("workflow", "step"), "exact", execute, ttl=60)
        self.assertFalse(first.cache_hit)
        self.assertTrue(second.cache_hit)
        self.assertEqual(second.value, {"answer": 42, "score": 0.5})
        self.assertEqual(calls, 1)

    def test_async_callable_executes_once(self) -> None:
        calls = 0

        async def execute() -> list:
            nonlocal calls
            calls += 1
            return ["cached", False, 0]

        async def exercise() -> tuple:
            return (
                await self.cache.ainvoke(("agent", "tool"), "k", execute, ttl=60),
                await self.cache.ainvoke(("agent", "tool"), "k", execute, ttl=60),
            )

        first, second = asyncio.run(exercise())
        self.assertFalse(first.cache_hit)
        self.assertTrue(second.cache_hit)
        self.assertEqual(second.value, ["cached", False, 0])
        self.assertEqual(calls, 1)

    def test_cached_null_is_distinguished_from_a_miss(self) -> None:
        calls = 0

        def execute() -> None:
            nonlocal calls
            calls += 1
            return None

        self.assertFalse(self.cache.invoke(("step",), "null", execute, ttl=60).cache_hit)
        outcome = self.cache.invoke(("step",), "null", execute, ttl=60)
        self.assertTrue(outcome.cache_hit)
        self.assertIsNone(outcome.value)
        self.assertEqual(calls, 1)

    def test_failed_execution_is_not_cached(self) -> None:
        key = ExecutionCacheKey(("step",), "failure")

        def fail() -> dict:
            raise RuntimeError("operation failed")

        with self.assertRaises(RuntimeError):
            self.cache.adapter.get_or_execute(key, fail, ttl=60)
        self.assertEqual(self.cache.adapter.get((key,)), {})

    def test_failed_encode_publishes_nothing(self) -> None:
        key = ExecutionCacheKey(("step",), "bad-json")
        for invalid in ({"bad": object()}, {1: "non-string key"}, float("nan"), "\ud800"):
            with self.subTest(invalid=type(invalid).__name__), self.assertRaises(ValueError):
                self.cache.adapter.set({key: (invalid, 60)})
        self.assertEqual(self.cache.adapter.get((key,)), {})

    def test_serializer_identifier_mismatch_fails_at_construction(self) -> None:
        class WrongCodec(PythonJsonCodec):
            serializer_id = "wrong/v1"

        with self.assertRaisesRegex(ValueError, "must match"):
            RuntimeCacheAdapter(self.bridge, WrongCodec())

    def test_wrong_type_tag_is_a_miss_then_executes(self) -> None:
        key = ExecutionCacheKey(("step",), "wrong-tag")
        self.bridge.set({key: (EncodedExecutionValue("bytes", b"{}"), 60)})
        outcome = self.cache.adapter.get_or_execute(
            key, lambda: {"recomputed": True}, ttl=60
        )
        self.assertFalse(outcome.cache_hit)
        self.assertEqual(outcome.value, {"recomputed": True})

    def test_ttl_clear_disable_and_partition_isolation(self) -> None:
        namespace = ("workflow",)
        calls = 0

        def execute() -> str:
            nonlocal calls
            calls += 1
            return "value"

        self.cache.invoke(namespace, "key", execute, ttl=10)
        self.clock.now += timedelta(seconds=11)
        self.assertFalse(self.cache.invoke(namespace, "key", execute, ttl=10).cache_hit)
        self.cache.clear([namespace])
        self.assertFalse(self.cache.invoke(namespace, "key", execute, ttl=10).cache_hit)
        self.cache.set_enabled(False)
        self.assertFalse(self.cache.invoke(namespace, "key", execute, ttl=10).cache_hit)

        other_bridge = ExecutionCacheBridge(
            runtime="python",
            serializer=PYTHON_JSON_SERIALIZER,
            authorization_partition=derive_authorization_partition(
                "tenant-b", ["project:python"], b"r" * 32
            ),
            stores=[self.store],
            publish_to=self.store,
            producer="python-runtime",
            clock=self.clock,
        )
        other = OnceMeshPythonCache(other_bridge)
        self.assertFalse(other.invoke(namespace, "key", lambda: "other", ttl=10).cache_hit)
        self.assertGreaterEqual(calls, 4)


if __name__ == "__main__":
    unittest.main()
