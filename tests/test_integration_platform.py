from __future__ import annotations

from contextlib import closing
import asyncio
import tempfile
import json
import sqlite3
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncemesh import (  # noqa: E402
    ExecutionCacheBridge,
    ExecutionCacheKey,
    FilesystemActiveKeyIndex,
    IndexedRuntimeCacheAdapter,
    MemoryActiveKeyIndex,
    SQLiteActiveKeyIndex,
    CoordinationTimeoutError,
    MemoryStore,
    RuntimeCacheAdapter,
    AdapterDescriptor,
    builtin_adapters,
    discover_adapters,
    derive_authorization_partition,
    get_adapter,
    load_adapter_class,
)
from oncemesh.integrations.codecs import JsonValueCodec  # noqa: E402
from oncemesh.integrations.conformance import (  # noqa: E402
    probe_exact_adapter,
    probe_indexed_adapter,
)


def make_indexed(
    store: MemoryStore,
    index: MemoryActiveKeyIndex | FilesystemActiveKeyIndex | SQLiteActiveKeyIndex,
) -> IndexedRuntimeCacheAdapter[dict]:
    bridge = ExecutionCacheBridge(
        runtime="test-kv",
        serializer="test.index-json/v1",
        authorization_partition=derive_authorization_partition(
            "tenant-a", ["project:index"], b"i" * 32
        ),
        stores=[store],
        publish_to=store,
        producer="index-test",
    )
    adapter: RuntimeCacheAdapter[dict] = RuntimeCacheAdapter(
        bridge, JsonValueCodec("test.index-json/v1")
    )
    return IndexedRuntimeCacheAdapter(adapter, index)


class AdapterRegistryTests(unittest.TestCase):
    def test_registry_lists_four_dependency_light_descriptors(self) -> None:
        descriptors = builtin_adapters()
        self.assertEqual(
            {descriptor.name for descriptor in descriptors},
            {"python", "langgraph", "langchain", "llamaindex"},
        )
        self.assertEqual(len({descriptor.module for descriptor in descriptors}), 4)
        self.assertEqual(get_adapter("llamaindex").extra, "llamaindex")
        self.assertEqual(discover_adapters(), descriptors)
        self.assertEqual(load_adapter_class("python").__name__, "OnceMeshPythonCache")
        with self.assertRaises(KeyError):
            get_adapter("unknown")

    def test_third_party_entry_point_discovery_is_explicit(self) -> None:
        descriptor = AdapterDescriptor(
            "widget",
            "Third-party test adapter.",
            "widget_oncemesh",
            "WidgetCache",
            "widget",
            "experimental",
            ("sync", "ttl"),
        )

        class EntryPoint:
            name = "widget"

            @staticmethod
            def load():
                return lambda: descriptor

        with patch(
            "oncemesh.integrations.registry.entry_points", return_value=[EntryPoint()]
        ):
            self.assertEqual(discover_adapters()[-1].name, "llamaindex")
            self.assertEqual(
                discover_adapters(include_plugins=True)[-1], descriptor
            )

    def test_legacy_imports_are_compatibility_aliases(self) -> None:
        from oncemesh.python_runtime import OnceMeshPythonCache as LegacyPython
        from oncemesh.runtime_adapter import RuntimeCacheAdapter as LegacyBase
        from oncemesh.integrations.python import OnceMeshPythonCache

        self.assertIs(LegacyPython, OnceMeshPythonCache)
        self.assertIs(LegacyBase, RuntimeCacheAdapter)
        try:
            from oncemesh.langgraph import OnceMeshLangGraphCache as LegacyLangGraph
            from oncemesh.integrations.langgraph import OnceMeshLangGraphCache
        except ImportError:
            return
        self.assertIs(LegacyLangGraph, OnceMeshLangGraphCache)


class ActiveKeyIndexTests(unittest.TestCase):
    def test_sqlite_shared_conformance_and_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "active-keys.sqlite3"
            store = MemoryStore("sqlite-conformance")
            adapter = make_indexed(store, SQLiteActiveKeyIndex(path))
            report = probe_indexed_adapter(
                adapter,
                namespace=("sqlite",),
                key="key",
                first={"version": 1},
                second={"version": 2},
            )
            self.assertTrue(report.passed)
            reopened = SQLiteActiveKeyIndex(path)
            self.assertEqual(reopened.integrity_check(), "ok")
            self.assertEqual(reopened.generation(("sqlite",), "key"), 3)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_sqlite_publication_failure_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            index = SQLiteActiveKeyIndex(Path(directory) / "active.sqlite3")
            adapter = make_indexed(MemoryStore("sqlite-rollback"), index)
            namespace = ("sqlite",)
            adapter.put(namespace, "key", {"version": 1}, ttl=None)
            revision = index.active_revision(namespace, "key")
            with patch.object(adapter.adapter.bridge, "set", side_effect=OSError("full")):
                with self.assertRaisesRegex(OSError, "full"):
                    adapter.put(namespace, "key", {"version": 2}, ttl=None)
            self.assertEqual(index.active_revision(namespace, "key"), revision)
            self.assertEqual(adapter.get(namespace, "key"), {"version": 1})
            self.assertEqual(index.integrity_check(), "ok")

    def test_sqlite_busy_timeout_is_bounded_and_typed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "active.sqlite3"
            index = SQLiteActiveKeyIndex(path, busy_timeout=0.05)
            holder = sqlite3.connect(path, isolation_level=None)
            try:
                holder.execute("BEGIN IMMEDIATE")
                with self.assertRaises(CoordinationTimeoutError):
                    index.prepare_put(("sqlite",), "key")
            finally:
                holder.rollback()
                holder.close()
            self.assertEqual(index.prepare_put(("sqlite",), "key"), 0)

    def test_sqlite_synchronous_profile_is_explicit_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "active.sqlite3"
            normal = SQLiteActiveKeyIndex(path)
            self.assertEqual(normal.synchronous, "NORMAL")
            full = SQLiteActiveKeyIndex(path, synchronous="FULL")
            self.assertEqual(full.synchronous, "FULL")
            with self.assertRaisesRegex(ValueError, "NORMAL or FULL"):
                SQLiteActiveKeyIndex(path, synchronous="OFF")

    def test_sqlite_indexed_adapter_async_contract(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as directory:
                index = SQLiteActiveKeyIndex(Path(directory) / "active.sqlite3")
                adapter = make_indexed(MemoryStore("sqlite-async"), index)
                namespace = ("sqlite-async",)
                await adapter.aput(namespace, "key", {"value": 1}, ttl=None)
                self.assertEqual(await adapter.aget(namespace, "key"), {"value": 1})
                self.assertEqual(await adapter.aget_all(namespace), {"key": {"value": 1}})
                self.assertTrue(await adapter.adelete(namespace, "key"))
                self.assertIsNone(await adapter.aget(namespace, "key"))
                await adapter.aput(namespace, "key", {"value": 2}, ttl=None)
                self.assertEqual(await adapter.aclear(namespace), 1)

        asyncio.run(scenario())

    def test_filesystem_to_sqlite_migration_is_explicit_and_source_preserving(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "active.json"
            source = FilesystemActiveKeyIndex(source_path)
            source.publish_and_activate(("migrated",), "active", lambda *_: None)
            source.prepare_put(("migrated",), "inactive")
            source_before = source_path.read_bytes()
            destination = SQLiteActiveKeyIndex(root / "active.sqlite3")
            self.assertEqual(destination.import_filesystem(source), 2)
            self.assertEqual(destination.active_keys(("migrated",)), ("active",))
            self.assertEqual(destination.generation(("migrated",), "inactive"), 0)
            self.assertEqual(source_path.read_bytes(), source_before)

            with self.assertRaisesRegex(ValueError, "not empty"):
                destination.import_filesystem(source)
            source.delete(("migrated",), "active")
            self.assertEqual(destination.import_filesystem(source, replace=True), 2)
            self.assertEqual(destination.active_keys(("migrated",)), ())
            self.assertEqual(destination.integrity_check(), "ok")

    def test_publication_failure_preserves_last_committed_value(self) -> None:
        store = MemoryStore("transaction-failure")
        index = MemoryActiveKeyIndex()
        adapter = make_indexed(store, index)
        namespace = ("collection",)
        adapter.put(namespace, "key", {"version": 1}, ttl=None)

        with patch.object(adapter.adapter.bridge, "set", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                adapter.put(namespace, "key", {"version": 2}, ttl=None)

        self.assertEqual(index.generation(namespace, "key"), 0)
        self.assertTrue(index.is_active(namespace, "key"))
        self.assertEqual(adapter.get(namespace, "key"), {"version": 1})

    def test_nonpublishing_puts_do_not_activate_index(self) -> None:
        index = MemoryActiveKeyIndex()
        adapter = make_indexed(MemoryStore("nonpublishing"), index)
        namespace = ("collection",)
        adapter.put(namespace, "zero", {"value": 1}, ttl=0)
        adapter.adapter.bridge.set_enabled(False)
        adapter.put(namespace, "disabled", {"value": 2}, ttl=None)
        self.assertEqual(index.active_keys(namespace), ())

    def test_indexed_clear_does_not_rotate_process_local_bridge_epochs(self) -> None:
        adapter = make_indexed(MemoryStore("clear-generation"), MemoryActiveKeyIndex())
        namespace = ("collection",)
        adapter.put(namespace, "key", {"value": 1}, ttl=None)
        before = adapter.adapter.bridge.epochs.epochs(namespace)
        self.assertEqual(adapter.clear(namespace), 1)
        self.assertEqual(adapter.adapter.bridge.epochs.epochs(namespace), before)

    def test_shared_exact_and_indexed_conformance_probes(self) -> None:
        store = MemoryStore("probes")
        indexed = make_indexed(store, MemoryActiveKeyIndex())
        exact_report = probe_exact_adapter(
            indexed.adapter,
            key=ExecutionCacheKey(("exact",), "key"),
            value={"value": 1},
        )
        indexed_report = probe_indexed_adapter(
            make_indexed(MemoryStore("indexed-probe"), MemoryActiveKeyIndex()),
            namespace=("indexed",),
            key="key",
            first={"version": 1},
            second={"version": 2},
        )
        self.assertTrue(exact_report.passed)
        self.assertTrue(indexed_report.passed)

    def test_overwrite_delete_reput_and_enumeration_do_not_resurrect(self) -> None:
        store = MemoryStore("indexed")
        index = MemoryActiveKeyIndex()
        adapter = make_indexed(store, index)
        namespace = ("collection",)

        adapter.put(namespace, "key", {"version": 1}, ttl=None)
        self.assertEqual(adapter.get(namespace, "key"), {"version": 1})
        self.assertEqual(index.generation(namespace, "key"), 0)

        adapter.put(namespace, "key", {"version": 2}, ttl=None)
        self.assertEqual(adapter.get(namespace, "key"), {"version": 2})
        self.assertEqual(index.generation(namespace, "key"), 1)
        self.assertEqual(adapter.get_all(namespace), {"key": {"version": 2}})

        self.assertTrue(adapter.delete(namespace, "key"))
        self.assertIsNone(adapter.get(namespace, "key"))
        self.assertFalse(adapter.delete(namespace, "key"))
        self.assertEqual(index.generation(namespace, "key"), 2)

        adapter.put(namespace, "key", {"version": 3}, ttl=None)
        self.assertEqual(adapter.get(namespace, "key"), {"version": 3})
        self.assertEqual(index.generation(namespace, "key"), 2)

    def test_collection_clear_is_narrow(self) -> None:
        adapter = make_indexed(MemoryStore("indexed"), MemoryActiveKeyIndex())
        left, right = ("left",), ("right",)
        adapter.put(left, "key", {"side": "left"}, ttl=None)
        adapter.put(right, "key", {"side": "right"}, ttl=None)
        self.assertEqual(adapter.clear(left), 1)
        self.assertIsNone(adapter.get(left, "key"))
        self.assertEqual(adapter.get(right, "key"), {"side": "right"})

    def test_filesystem_index_reopen_preserves_state_and_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "active-keys.json"
            first = FilesystemActiveKeyIndex(path)
            namespace = ("collection",)
            self.assertEqual(first.prepare_put(namespace, "key"), 0)
            first.activate(namespace, "key")

            second = FilesystemActiveKeyIndex(path)
            self.assertTrue(second.is_active(namespace, "key"))
            self.assertEqual(second.active_keys(namespace), ("key",))
            self.assertTrue(second.delete(namespace, "key"))

            third = FilesystemActiveKeyIndex(path)
            self.assertFalse(third.is_active(namespace, "key"))
            self.assertEqual(third.generation(namespace, "key"), 1)
            self.assertEqual(third.prepare_put(namespace, "key"), 1)
            third.activate(namespace, "key")
            self.assertEqual(FilesystemActiveKeyIndex(path).active_keys(namespace), ("key",))

    def test_filesystem_index_reads_v1_and_upgrades_on_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "active-keys.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "entries": [
                            {
                                "namespace": ["legacy"],
                                "key": "key",
                                "generation": 4,
                                "active": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            index = FilesystemActiveKeyIndex(path)
            self.assertEqual(index.active_revision(("legacy",), "key"), (4, None))
            self.assertTrue(index.delete(("legacy",), "key"))
            upgraded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(upgraded["version"], 2)
            self.assertIsNone(upgraded["entries"][0]["publication_id"])


if __name__ == "__main__":
    unittest.main()
