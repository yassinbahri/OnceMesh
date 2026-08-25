"""Produce repeatable M6 evidence for the open adapter platform."""

from __future__ import annotations

from datetime import datetime, timezone
from importlib.metadata import version
import json
from pathlib import Path
import sys
import tempfile
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from langchain_core.globals import set_llm_cache  # noqa: E402
from langchain_core.language_models.fake import FakeListLLM  # noqa: E402
from llama_index.core.ingestion import IngestionCache  # noqa: E402
from llama_index.core.schema import TextNode  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.types import CachePolicy  # noqa: E402

from oncemesh import (  # noqa: E402
    ExecutionCacheBridge,
    ExecutionCacheKey,
    FilesystemActiveKeyIndex,
    MemoryActiveKeyIndex,
    MemoryStore,
    OnceMeshPythonCache,
    PYTHON_JSON_SERIALIZER,
    RuntimeCacheAdapter,
    SQLiteActiveKeyIndex,
    builtin_adapters,
    derive_authorization_partition,
)
from oncemesh.integrations.codecs import JsonValueCodec  # noqa: E402
from oncemesh.integrations.conformance import (  # noqa: E402
    probe_exact_adapter,
    probe_indexed_adapter,
)
from oncemesh.integrations.index import IndexedRuntimeCacheAdapter  # noqa: E402
from oncemesh.integrations.langchain import (  # noqa: E402
    LANGCHAIN_SERIALIZER,
    OnceMeshLangChainCache,
)
from oncemesh.integrations.langgraph import OnceMeshLangGraphCache  # noqa: E402
from oncemesh.integrations.llamaindex import (  # noqa: E402
    LLAMAINDEX_SERIALIZER,
    OnceMeshLlamaIndexKVStore,
)


PARTITION = derive_authorization_partition(
    "tenant-a", ["project:adapter-platform"], b"m" * 32
)


def make_bridge(store: MemoryStore, runtime: str, serializer: str) -> ExecutionCacheBridge:
    return ExecutionCacheBridge(
        runtime=runtime,
        serializer=serializer,
        authorization_partition=PARTITION,
        stores=[store],
        publish_to=store,
        producer="m6-adapter-platform",
    )


def main() -> int:
    checks: list[dict[str, object]] = []

    def record(name: str, passed: bool, detail: object) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    descriptors = builtin_adapters()
    record(
        "four_dependency_light_descriptors",
        {item.name for item in descriptors}
        == {"python", "langgraph", "langchain", "llamaindex"},
        [item.name for item in descriptors],
    )

    python_store = MemoryStore("python")
    python_bridge = make_bridge(python_store, "python", PYTHON_JSON_SERIALIZER)
    python_cache = OnceMeshPythonCache(python_bridge)
    calls = 0

    def execute() -> dict:
        nonlocal calls
        calls += 1
        return {"answer": 42}

    first = python_cache.invoke(("agent",), "exact", execute, ttl=60)
    second = python_cache.invoke(("agent",), "exact", execute, ttl=60)
    record(
        "native_python_shared_sdk",
        not first.cache_hit and second.cache_hit and calls == 1,
        {"executions": calls},
    )

    exact_adapter = RuntimeCacheAdapter(
        make_bridge(MemoryStore("exact-probe"), "probe", "probe.json/v1"),
        JsonValueCodec("probe.json/v1"),
    )
    exact_report = probe_exact_adapter(
        exact_adapter,
        key=ExecutionCacheKey(("probe",), "exact"),
        value={"value": 1},
    )
    indexed_adapter = IndexedRuntimeCacheAdapter(
        RuntimeCacheAdapter(
            make_bridge(MemoryStore("indexed-probe"), "probe-kv", "probe.kv-json/v1"),
            JsonValueCodec("probe.kv-json/v1"),
        ),
        MemoryActiveKeyIndex(),
    )
    indexed_report = probe_indexed_adapter(
        indexed_adapter,
        namespace=("collection",),
        key="key",
        first={"version": 1},
        second={"version": 2},
    )
    record(
        "shared_conformance_profiles",
        exact_report.passed and indexed_report.passed,
        {"exact": len(exact_report.checks), "indexed": len(indexed_report.checks)},
    )

    langchain_cache = OnceMeshLangChainCache(
        make_bridge(MemoryStore("langchain"), "langchain", LANGCHAIN_SERIALIZER),
        ttl=60,
    )
    set_llm_cache(langchain_cache)
    try:
        model = FakeListLLM(responses=["first", "second"], cache=True)
        model_first = model.invoke("same")
        model_second = model.invoke("same")
        model_different = model.invoke("different")
    finally:
        set_llm_cache(None)
    record(
        "real_langchain_model_cache",
        (model_first, model_second, model_different) == ("first", "first", "second"),
        [model_first, model_second, model_different],
    )

    class GraphState(TypedDict, total=False):
        number: int
        doubled: int

    graph_calls = 0

    def graph_operation(state: GraphState) -> dict[str, int]:
        nonlocal graph_calls
        graph_calls += 1
        return {"doubled": state["number"] * 2}

    graph_builder = StateGraph(GraphState)
    graph_builder.add_node(
        "expensive", graph_operation, cache_policy=CachePolicy(ttl=60)
    )
    graph_builder.add_edge(START, "expensive")
    graph_builder.add_edge("expensive", END)
    graph_cache = OnceMeshLangGraphCache(
        make_bridge(
            MemoryStore("langgraph"),
            "langgraph",
            "langgraph.jsonplus/no-pickle-v1",
        )
    )
    graph = graph_builder.compile(cache=graph_cache)
    graph_first = graph.invoke({"number": 21})
    graph_second = graph.invoke({"number": 21})
    record(
        "real_langgraph_node_cache",
        graph_first == graph_second == {"number": 21, "doubled": 42}
        and graph_calls == 1,
        {"executions": graph_calls},
    )

    llama_store = MemoryStore("llamaindex")
    llama_bridge = make_bridge(llama_store, "llamaindex", LLAMAINDEX_SERIALIZER)
    llama_backend = OnceMeshLlamaIndexKVStore(llama_bridge, ttl=60)
    ingestion = IngestionCache(cache=llama_backend, collection="ingestion")
    ingestion.put("document", [TextNode(text="OnceMesh reusable node")])
    nodes = ingestion.get("document")
    ingestion.clear()
    record(
        "real_llamaindex_ingestion_cache",
        nodes is not None
        and nodes[0].get_content() == "OnceMesh reusable node"
        and ingestion.get("document") is None,
        "round trip and clear",
    )

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "active.json"
        first_index = FilesystemActiveKeyIndex(path)
        first_index.prepare_put(("collection",), "key")
        first_index.activate(("collection",), "key")
        second_index = FilesystemActiveKeyIndex(path)
        reopened = second_index.is_active(("collection",), "key")
        second_index.delete(("collection",), "key")
        third_index = FilesystemActiveKeyIndex(path)
        generation = third_index.generation(("collection",), "key")
    record(
        "filesystem_index_reopen_and_delete_generation",
        reopened and generation == 1,
        {"generation": generation},
    )

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = FilesystemActiveKeyIndex(root / "active.json")
        source.publish_and_activate(("collection",), "key", lambda *_: None)
        sqlite_index = SQLiteActiveKeyIndex(root / "active.sqlite3")
        imported = sqlite_index.import_filesystem(source)
        sqlite_reopened = SQLiteActiveKeyIndex(root / "active.sqlite3")
        sqlite_active = sqlite_reopened.active_keys(("collection",))
        sqlite_integrity = sqlite_reopened.integrity_check()
    record(
        "sqlite_wal_migration_reopen_and_integrity",
        imported == 1 and sqlite_active == ("key",) and sqlite_integrity == "ok",
        {"imported": imported, "active": list(sqlite_active), "integrity": sqlite_integrity},
    )

    framework_files = [
        ROOT / "src" / "oncemesh" / "integrations" / name
        for name in ("python.py", "langgraph.py", "langchain.py", "llamaindex.py")
    ]
    forbidden = ("from ..store", "publish_result(", "reuse(")
    thin = all(
        not any(token in path.read_text(encoding="utf-8") for token in forbidden)
        for path in framework_files
    )
    record("framework_modules_do_not_own_policy", thin, "no direct store or reuse calls")

    report = {
        "spec_version": "oncemesh.evaluation/adapter-platform-v0",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "environment_kind": "local-real-frameworks",
        "frameworks": {
            "langchain-core": version("langchain-core"),
            "langgraph": version("langgraph"),
            "llama-index-core": version("llama-index-core"),
        },
        "checks": checks,
        "passed": all(bool(check["passed"]) for check in checks),
    }
    output = ROOT / "evaluation" / "results" / "adapter-platform-20260824.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
