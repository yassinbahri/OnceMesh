"""Produce repeatable M5 evidence for two runtime integrations."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from importlib.metadata import version
import json
from pathlib import Path
import sys
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.types import CachePolicy  # noqa: E402

from oncemesh import (  # noqa: E402
    ExecutionCacheBridge,
    MemoryStore,
    OnceMeshPythonCache,
    PYTHON_JSON_SERIALIZER,
    PythonJsonCodec,
    RuntimeCacheAdapter,
    derive_authorization_partition,
)
from oncemesh.langgraph import OnceMeshLangGraphCache  # noqa: E402


def bridge(store: MemoryStore, runtime: str, serializer: str) -> ExecutionCacheBridge:
    return ExecutionCacheBridge(
        runtime=runtime,
        serializer=serializer,
        authorization_partition=derive_authorization_partition(
            "tenant-a", ["project:adapter-evaluation"], b"a" * 32
        ),
        stores=[store],
        publish_to=store,
        producer="m5-adapter-evaluation",
    )


def main() -> int:
    checks: list[dict[str, object]] = []

    def record(name: str, passed: bool, detail: object) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    python_store = MemoryStore("python-project")
    python_bridge = bridge(python_store, "python", PYTHON_JSON_SERIALIZER)
    python_cache = OnceMeshPythonCache(python_bridge)
    sync_calls = 0

    def sync_operation() -> dict:
        nonlocal sync_calls
        sync_calls += 1
        return {"answer": 42, "confidence": 0.75}

    sync_first = python_cache.invoke(("agent", "extract"), "input-v1", sync_operation, ttl=300)
    sync_second = python_cache.invoke(("agent", "extract"), "input-v1", sync_operation, ttl=300)
    record(
        "python_sync_one_execution",
        not sync_first.cache_hit and sync_second.cache_hit and sync_calls == 1,
        {"executions": sync_calls},
    )

    async_calls = 0

    async def async_operation() -> list:
        nonlocal async_calls
        async_calls += 1
        return ["normalized", False, 0]

    async def python_async_twice() -> tuple:
        return (
            await python_cache.ainvoke(("agent", "async"), "input-v1", async_operation, ttl=300),
            await python_cache.ainvoke(("agent", "async"), "input-v1", async_operation, ttl=300),
        )

    async_first, async_second = asyncio.run(python_async_twice())
    record(
        "python_async_one_execution",
        not async_first.cache_hit and async_second.cache_hit and async_calls == 1,
        {"executions": async_calls},
    )

    null_calls = 0

    def null_operation() -> None:
        nonlocal null_calls
        null_calls += 1
        return None

    python_cache.invoke(("agent", "null"), "input-v1", null_operation, ttl=300)
    null_second = python_cache.invoke(("agent", "null"), "input-v1", null_operation, ttl=300)
    record(
        "falsey_value_is_a_hit",
        null_second.cache_hit and null_second.value is None and null_calls == 1,
        {"executions": null_calls},
    )

    before_failures = sum(len(items) for items in python_store._results.values())
    failed = False
    try:
        python_cache.invoke(
            ("agent", "failure"),
            "input-v1",
            lambda: (_ for _ in ()).throw(RuntimeError("expected")),
            ttl=300,
        )
    except RuntimeError:
        failed = True
    after_failures = sum(len(items) for items in python_store._results.values())
    record(
        "failed_operation_not_published",
        failed and before_failures == after_failures,
        {"manifest_count": after_failures},
    )

    mismatch_rejected = False

    class WrongCodec(PythonJsonCodec):
        serializer_id = "wrong/v1"

    try:
        RuntimeCacheAdapter(python_bridge, WrongCodec())
    except ValueError:
        mismatch_rejected = True
    record("serializer_mismatch_rejected", mismatch_rejected, "construction failed closed")

    langgraph_store = MemoryStore("langgraph-project")
    langgraph_bridge = bridge(
        langgraph_store, "langgraph", "langgraph.jsonplus/no-pickle-v1"
    )
    langgraph_cache = OnceMeshLangGraphCache(langgraph_bridge)

    class GraphState(TypedDict, total=False):
        number: int
        doubled: int

    graph_calls = 0

    def graph_operation(state: GraphState) -> dict[str, int]:
        nonlocal graph_calls
        graph_calls += 1
        return {"doubled": state["number"] * 2}

    builder = StateGraph(GraphState)
    builder.add_node("expensive", graph_operation, cache_policy=CachePolicy(ttl=300))
    builder.add_edge(START, "expensive")
    builder.add_edge("expensive", END)
    graph = builder.compile(cache=langgraph_cache)
    graph_first = graph.invoke({"number": 21})
    graph_second = graph.invoke({"number": 21})
    record(
        "langgraph_uses_shared_sdk",
        graph_first == graph_second == {"number": 21, "doubled": 42} and graph_calls == 1,
        {"executions": graph_calls},
    )

    report = {
        "spec_version": "oncemesh.evaluation/runtime-adapters-v0",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "environment_kind": "local-real-runtime",
        "integrations": ["native-python", "langgraph"],
        "frameworks": {"langgraph": version("langgraph")},
        "checks": checks,
        "passed": all(bool(check["passed"]) for check in checks),
    }
    output = ROOT / "evaluation" / "results" / "runtime-adapters-20260824.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
