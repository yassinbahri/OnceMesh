from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    from llama_index.core.ingestion import IngestionCache
    from llama_index.core.schema import TextNode
    from oncemesh.integrations.llamaindex import (
        LLAMAINDEX_SERIALIZER,
        OnceMeshLlamaIndexKVStore,
    )
except ImportError:  # pragma: no cover - optional dependency
    OnceMeshLlamaIndexKVStore = None

from oncemesh import (  # noqa: E402
    ExecutionCacheBridge,
    FilesystemActiveKeyIndex,
    MemoryStore,
    derive_authorization_partition,
)


@unittest.skipIf(OnceMeshLlamaIndexKVStore is None, "LlamaIndex optional dependency is not installed")
class LlamaIndexAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemoryStore("llamaindex")

    def bridge(self) -> ExecutionCacheBridge:
        return ExecutionCacheBridge(
            runtime="llamaindex",
            serializer=LLAMAINDEX_SERIALIZER,
            authorization_partition=derive_authorization_partition(
                "tenant-a", ["project:llamaindex"], b"x" * 32
            ),
            stores=[self.store],
            publish_to=self.store,
            producer="llamaindex-runtime",
        )

    def test_real_kv_contract_overwrite_enumerate_delete_and_async(self) -> None:
        cache = OnceMeshLlamaIndexKVStore(self.bridge(), ttl=60)
        cache.put("a", {"value": 1}, collection="alpha")
        cache.put("a", {"value": 2}, collection="alpha")
        cache.put_all(
            [("b", {"value": 3}), ("batch", {"value": 9})],
            collection="alpha",
            batch_size=2,
        )
        self.assertEqual(
            cache.get_all("alpha"),
            {"a": {"value": 2}, "b": {"value": 3}, "batch": {"value": 9}},
        )
        self.assertTrue(cache.delete("a", "alpha"))
        self.assertIsNone(cache.get("a", "alpha"))
        cache.put("a", {"value": 4}, collection="alpha")
        self.assertEqual(cache.get("a", "alpha"), {"value": 4})

        async def exercise() -> None:
            await cache.aput_all([("c", {"value": 5})], "alpha", batch_size=1)
            self.assertEqual(await cache.aget("c", "alpha"), {"value": 5})
            self.assertTrue(await cache.adelete("c", "alpha"))

        asyncio.run(exercise())

    def test_real_ingestion_cache_round_trip_and_clear(self) -> None:
        backend = OnceMeshLlamaIndexKVStore(self.bridge(), ttl=60)
        cache = IngestionCache(cache=backend, collection="ingestion")
        cache.put("document", [TextNode(text="OnceMesh reusable node")])
        nodes = cache.get("document")
        self.assertIsNotNone(nodes)
        self.assertEqual(nodes[0].get_content(), "OnceMesh reusable node")
        cache.clear()
        self.assertIsNone(cache.get("document"))

    def test_filesystem_index_reopen_preserves_ingestion_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "llama-active.json"
            first = OnceMeshLlamaIndexKVStore(
                self.bridge(), index=FilesystemActiveKeyIndex(path), ttl=60
            )
            first.put("document", {"nodes": [{"text": "value"}]}, "ingestion")
            second = OnceMeshLlamaIndexKVStore(
                self.bridge(), index=FilesystemActiveKeyIndex(path), ttl=60
            )
            self.assertEqual(
                second.get("document", "ingestion"), {"nodes": [{"text": "value"}]}
            )


if __name__ == "__main__":
    unittest.main()
