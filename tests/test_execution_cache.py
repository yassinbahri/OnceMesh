from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncemesh import (  # noqa: E402
    EncodedExecutionValue,
    ExecutionCacheBridge,
    ExecutionCacheKey,
    FilesystemEpochRegistry,
    FederationCacheStore,
    MemoryStore,
    action_digest,
    derive_authorization_partition,
    pack_execution_value,
    unpack_execution_value,
)


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


class ExecutionCacheBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemoryStore("project")
        self.clock = MutableClock()
        self.partition = derive_authorization_partition(
            "tenant-a", ["project:alpha"], b"p" * 32
        )
        self.bridge = ExecutionCacheBridge(
            runtime="generic-python",
            serializer="test.bytes/v1",
            authorization_partition=self.partition,
            stores=[self.store],
            publish_to=self.store,
            producer="project-runtime",
            clock=self.clock,
        )
        self.key = ExecutionCacheKey(("workflow", "node-a"), "exact-key")
        self.value = EncodedExecutionValue("json", b'{"answer":42}')

    def test_pack_round_trip_and_rejects_invalid_envelopes(self) -> None:
        self.assertEqual(unpack_execution_value(pack_execution_value(self.value)), self.value)
        for invalid in (b"", b"\x00\x00\x00\x00x", b"\x00\x00\x04\x01x"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                unpack_execution_value(invalid)

    def test_exact_value_round_trip_with_ttl(self) -> None:
        self.bridge.set({self.key: (self.value, 60)})
        self.assertEqual(self.bridge.get([self.key]), {self.key: self.value})
        self.clock.now += timedelta(seconds=61)
        self.assertEqual(self.bridge.get([self.key]), {})

    def test_null_ttl_is_private_non_expiring_entry(self) -> None:
        self.bridge.set({self.key: (self.value, None)})
        self.clock.now += timedelta(days=365)
        self.assertEqual(self.bridge.get([self.key]), {self.key: self.value})

    def test_non_positive_ttl_is_not_published(self) -> None:
        self.bridge.set({self.key: (self.value, 0)})
        self.assertEqual(self.bridge.get([self.key]), {})

    def test_identity_varies_by_runtime_serializer_and_partition(self) -> None:
        base = action_digest(self.bridge.action_for(self.key))
        variants = []
        for runtime, serializer, tenant in (
            ("other-runtime", "test.bytes/v1", "tenant-a"),
            ("generic-python", "other-codec/v1", "tenant-a"),
            ("generic-python", "test.bytes/v1", "tenant-b"),
        ):
            partition = derive_authorization_partition(tenant, ["project:alpha"], b"p" * 32)
            other = ExecutionCacheBridge(
                runtime=runtime,
                serializer=serializer,
                authorization_partition=partition,
                stores=[self.store],
                publish_to=self.store,
                producer="project-runtime",
                clock=self.clock,
            )
            variants.append(action_digest(other.action_for(self.key)))
        self.assertNotIn(base, variants)
        self.assertEqual(len(set(variants)), len(variants))

    def test_manifest_contains_neither_raw_tenant_nor_payload(self) -> None:
        self.bridge.set({self.key: (self.value, 60)})
        manifest = self.store.candidates(action_digest(self.bridge.action_for(self.key)))[0]
        encoded = json.dumps(manifest, sort_keys=True)
        self.assertNotIn("tenant-a", encoded)
        self.assertNotIn("answer", encoded)

    def test_partition_isolation(self) -> None:
        self.bridge.set({self.key: (self.value, 60)})
        other = ExecutionCacheBridge(
            runtime="generic-python",
            serializer="test.bytes/v1",
            authorization_partition=derive_authorization_partition(
                "tenant-b", ["project:alpha"], b"p" * 32
            ),
            stores=[self.store],
            publish_to=self.store,
            producer="project-runtime",
            clock=self.clock,
        )
        self.assertEqual(other.get([self.key]), {})

    def test_disable_is_live_and_non_destructive(self) -> None:
        self.bridge.set({self.key: (self.value, 60)})
        self.bridge.set_enabled(False)
        self.assertEqual(self.bridge.get([self.key]), {})
        self.bridge.set({self.key: (EncodedExecutionValue("json", b"new"), 60)})
        self.bridge.set_enabled(True)
        self.assertEqual(self.bridge.get([self.key]), {self.key: self.value})

    def test_namespace_and_global_clear_rotate_identity(self) -> None:
        other_key = ExecutionCacheKey(("workflow", "node-b"), "exact-key")
        self.bridge.set({self.key: (self.value, 60), other_key: (self.value, 60)})
        self.bridge.clear([self.key.namespace])
        self.assertEqual(self.bridge.get([self.key]), {})
        self.assertEqual(self.bridge.get([other_key]), {other_key: self.value})
        self.bridge.clear()
        self.assertEqual(self.bridge.get([other_key]), {})

    def test_corrupt_value_is_a_miss(self) -> None:
        self.bridge.set({self.key: (self.value, 60)})
        digest = next(iter(self.store._blobs))
        self.store._blobs[digest] = b"corrupt"
        self.assertEqual(self.bridge.get([self.key]), {})

    def test_untrusted_producer_is_a_miss(self) -> None:
        writer = ExecutionCacheBridge(
            runtime="generic-python",
            serializer="test.bytes/v1",
            authorization_partition=self.partition,
            stores=[self.store],
            publish_to=self.store,
            producer="untrusted-runtime",
            epochs=self.bridge.epochs,
            clock=self.clock,
        )
        writer.set({self.key: (self.value, 60)})
        self.assertEqual(self.bridge.get([self.key]), {})

    def test_filesystem_epochs_survive_registry_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "epochs.json"
            first = FilesystemEpochRegistry(path)
            first.rotate_namespaces([self.key.namespace])
            second = FilesystemEpochRegistry(path)
            self.assertEqual(second.epochs(self.key.namespace), (0, 1))
            second.rotate_all()
            self.assertEqual(first.epochs(self.key.namespace), (1, 1))

    def test_rejects_raw_or_malformed_partition(self) -> None:
        with self.assertRaises(ValueError):
            ExecutionCacheBridge(
                runtime="generic-python",
                serializer="test.bytes/v1",
                authorization_partition="tenant-a",
                stores=[self.store],
                publish_to=self.store,
                producer="project-runtime",
            )

    def test_federation_store_is_rejected_at_the_boundary(self) -> None:
        federation = FederationCacheStore()
        with self.assertRaisesRegex(ValueError, "cannot use a federation store"):
            ExecutionCacheBridge(
                runtime="generic-python",
                serializer="test.bytes/v1",
                authorization_partition=self.partition,
                stores=[federation],
                publish_to=self.store,
                producer="project-runtime",
            )


if __name__ == "__main__":
    unittest.main()
