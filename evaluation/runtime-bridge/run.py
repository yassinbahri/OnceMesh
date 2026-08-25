"""Produce repeatable local evidence for the M4 execution-cache bridge."""

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
    EncodedExecutionValue,
    ExecutionCacheBridge,
    ExecutionCacheKey,
    FederationCacheStore,
    MemoryStore,
    derive_authorization_partition,
)
from oncemesh.langgraph import OnceMeshLangGraphCache  # noqa: E402


def make_bridge(store: MemoryStore, tenant: str) -> ExecutionCacheBridge:
    return ExecutionCacheBridge(
        runtime="langgraph",
        serializer="langgraph.jsonplus/no-pickle-v1",
        authorization_partition=derive_authorization_partition(
            tenant, ["project:runtime-evaluation"], b"m4-evaluation-partition-key-0001"
        ),
        stores=[store],
        publish_to=store,
        producer="m4-runtime-evaluation",
    )


def main() -> int:
    checks: list[dict[str, object]] = []

    def record(name: str, passed: bool, detail: object) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    store = MemoryStore("project")
    bridge = make_bridge(store, "tenant-a")
    generic_key = ExecutionCacheKey(("generic", "step"), "same-input")
    generic_value = EncodedExecutionValue("json", b'{"value":42}')
    bridge.set({generic_key: (generic_value, 300)})
    record("framework_neutral_round_trip", bridge.get([generic_key]) == {generic_key: generic_value}, "typed bytes")

    other_partition = make_bridge(store, "tenant-b")
    record("cross_partition_miss", other_partition.get([generic_key]) == {}, "tenant-b cannot observe tenant-a")

    federation_rejected = False
    try:
        ExecutionCacheBridge(
            runtime="generic",
            serializer="bytes/v1",
            authorization_partition=bridge.authorization_partition,
            stores=[FederationCacheStore()],
            publish_to=store,
            producer="m4-runtime-evaluation",
        )
    except ValueError:
        federation_rejected = True
    record("public_federation_rejected", federation_rejected, "generic runtime values stay private")

    class SyncState(TypedDict, total=False):
        number: int
        doubled: int

    sync_calls = 0

    def expensive_sync(state: SyncState) -> dict[str, int]:
        nonlocal sync_calls
        sync_calls += 1
        return {"doubled": state["number"] * 2}

    cache = OnceMeshLangGraphCache(bridge)
    sync_builder = StateGraph(SyncState)
    sync_builder.add_node("expensive", expensive_sync, cache_policy=CachePolicy(ttl=300))
    sync_builder.add_edge(START, "expensive")
    sync_builder.add_edge("expensive", END)
    sync_graph = sync_builder.compile(cache=cache)
    sync_first = sync_graph.invoke({"number": 21})
    sync_second = sync_graph.invoke({"number": 21})
    record(
        "langgraph_sync_exact_reuse",
        sync_first == sync_second == {"number": 21, "doubled": 42} and sync_calls == 1,
        {"node_executions": sync_calls},
    )

    class AsyncState(TypedDict, total=False):
        text: str
        normalized: str

    async_calls = 0

    async def expensive_async(state: AsyncState) -> dict[str, str]:
        nonlocal async_calls
        async_calls += 1
        return {"normalized": state["text"].strip().lower()}

    async_builder = StateGraph(AsyncState)
    async_builder.add_node("expensive", expensive_async, cache_policy=CachePolicy(ttl=300))
    async_builder.add_edge(START, "expensive")
    async_builder.add_edge("expensive", END)
    async_graph = async_builder.compile(cache=cache)

    async def invoke_twice() -> tuple[dict, dict]:
        return (
            await async_graph.ainvoke({"text": " OnceMesh "}),
            await async_graph.ainvoke({"text": " OnceMesh "}),
        )

    async_first, async_second = asyncio.run(invoke_twice())
    record(
        "langgraph_async_exact_reuse",
        async_first == async_second == {"text": " OnceMesh ", "normalized": "oncemesh"}
        and async_calls == 1,
        {"node_executions": async_calls},
    )

    bridge.set_enabled(False)
    record("live_disable_miss", bridge.get([generic_key]) == {}, "stored value retained")
    bridge.set_enabled(True)
    bridge.clear([generic_key.namespace])
    record("namespace_clear_miss", bridge.get([generic_key]) == {}, "epoch rotated")

    manifests = [manifest for candidates in store._results.values() for manifest in candidates]
    public_text = json.dumps(manifests, sort_keys=True)
    record(
        "manifest_secret_minimization",
        "tenant-a" not in public_text and "tenant-b" not in public_text and '"value":42' not in public_text,
        "no raw tenant or payload in manifests",
    )

    report = {
        "spec_version": "oncemesh.evaluation/runtime-bridge-v0",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "environment_kind": "local-real-framework",
        "frameworks": {"langgraph": version("langgraph")},
        "core_contract": "framework-neutral",
        "checks": checks,
        "passed": all(bool(check["passed"]) for check in checks),
    }
    output = ROOT / "evaluation" / "results" / "runtime-bridge-20260824.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
