from __future__ import annotations

from copy import deepcopy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncemesh import (  # noqa: E402
    FederationCacheStore, FederationPeerConfig, FilesystemFederationCacheStore, MemoryStore,
    PublicPeerCatalog, action_digest, digest_bytes, import_from_peer,
    manifest_digest, publish_signed_result, raw_public_key, sign_availability, verify_availability,
)


def echo_action(text="hello"):
    return {
        "spec_version": "oncemesh.action/v0",
        "operation": {"name": "example.echo", "version": "1"},
        "inputs": {"text": text},
        "executor": {"name": "example", "version": "1", "config": {}},
        "output_schema": "example.text/v1",
        "vary": {},
    }


class PeerWrapper:
    def __init__(self, peer, *, availability_mutator=None, bundle_mutator=None):
        self.peer = peer
        self.availability_mutator = availability_mutator
        self.bundle_mutator = bundle_mutator

    def availability(self, now=None):
        value = self.peer.availability(now)
        if self.availability_mutator:
            self.availability_mutator(value)
        return value

    def fetch_bundle(self, result_digest):
        value = self.peer.fetch_bundle(result_digest)
        if value and self.bundle_mutator:
            self.bundle_mutator(value)
        return value


class FederationExperimentTests(unittest.TestCase):
    RECEIPT_SEED = bytes.fromhex("77" * 32)
    AVAILABILITY_SEED = bytes.fromhex("66" * 32)

    def setUp(self):
        self.now = datetime(2026, 8, 24, 21, tzinfo=timezone.utc)
        self.current = self.now
        self.origin = MemoryStore("org-a-origin")
        self.receipt_public = raw_public_key(self.RECEIPT_SEED)
        self.receipt_key_id = digest_bytes(self.receipt_public)
        self.availability_public = raw_public_key(self.AVAILABILITY_SEED)
        self.action = echo_action()
        self.manifest, self.receipt = self.publish_result(self.action, b"hello")
        self.catalog = PublicPeerCatalog(
            "org-a", self.origin, self.AVAILABILITY_SEED,
            {self.receipt_key_id: self.receipt_public},
        )
        self.result_digest = self.catalog.publish(
            self.action, self.manifest, self.receipt, classification="public"
        )
        self.destination = FederationCacheStore("org-b-federation", clock=lambda: self.current)

    def publish_result(self, action, output):
        return publish_signed_result(
            self.origin, action, {"result": (output, "text/plain")},
            producer="org-a:producer", produced_at=self.now,
            fresh_until=self.now + timedelta(hours=1),
            executor_environment={"implementation": "org-a-test"},
            private_key=self.RECEIPT_SEED,
        )

    def config(self, **overrides):
        values = {
            "peer_id": "org-a",
            "availability_public_key": self.availability_public,
            "receipt_public_keys": {self.receipt_key_id: self.receipt_public},
            "trusted_producers": frozenset({"org-a:producer"}),
            "allowed_operations": frozenset({"example.echo/1"}),
            "max_entries": 100,
            "max_artifact_bytes": 1000,
            "max_transfer_bytes": 1000,
            "max_availability_age_seconds": 300,
            "max_future_clock_skew_seconds": 30,
            "retention_seconds": 60,
        }
        values.update(overrides)
        return FederationPeerConfig(**values)

    def test_two_explicit_organizations_exchange_exact_public_result(self):
        availability = self.catalog.availability(self.now)
        self.assertTrue(verify_availability(availability, "org-a", self.availability_public))
        outcome = import_from_peer(
            self.action, self.catalog, self.config(), self.destination, now=self.now
        )
        self.assertTrue(outcome.hit)
        self.assertEqual(outcome.result_digest, manifest_digest(self.manifest))
        imported = self.destination.candidates(action_digest(self.action))
        self.assertEqual(imported, [self.manifest])
        descriptor = self.manifest["artifacts"][0]
        self.assertEqual(self.destination.get_blob(descriptor["digest"]), b"hello")
        self.assertEqual(self.destination.receipts(self.result_digest), [self.receipt])

    def test_non_public_classification_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "explicitly public"):
            self.catalog.publish(self.action, self.manifest, self.receipt, classification="internal")

    def test_untrusted_availability_identity_fails_closed(self):
        other_key = raw_public_key(bytes.fromhex("55" * 32))
        outcome = import_from_peer(
            self.action, self.catalog, self.config(availability_public_key=other_key),
            self.destination, now=self.now,
        )
        self.assertEqual(outcome.reason, "availability_untrusted")

    def test_replayed_and_future_availability_fail_closed(self):
        class FixedAvailabilityPeer:
            def __init__(inner, availability):
                inner.fixed = availability

            def availability(inner, now=None):
                return deepcopy(inner.fixed)

            def fetch_bundle(inner, result_digest):
                return self.catalog.fetch_bundle(result_digest)

        old = self.catalog.availability(self.now - timedelta(minutes=6))
        replayed = import_from_peer(
            self.action, FixedAvailabilityPeer(old), self.config(), self.destination, now=self.now
        )
        self.assertEqual(replayed.reason, "availability_expired")

        future = self.catalog.availability(self.now + timedelta(seconds=31))
        from_future = import_from_peer(
            self.action, FixedAvailabilityPeer(future), self.config(), self.destination, now=self.now
        )
        self.assertEqual(from_future.reason, "availability_from_future")

    def test_tampered_availability_and_blob_fail_closed(self):
        tampered_availability = PeerWrapper(
            self.catalog, availability_mutator=lambda value: value.__setitem__("peer_id", "attacker")
        )
        first = import_from_peer(
            self.action, tampered_availability, self.config(), self.destination, now=self.now
        )
        self.assertEqual(first.reason, "availability_untrusted")

        def alter(bundle):
            bundle.artifacts["result"] = b"HELLO"

        tampered_blob = PeerWrapper(self.catalog, bundle_mutator=alter)
        second = import_from_peer(
            self.action, tampered_blob, self.config(), self.destination, now=self.now
        )
        self.assertEqual(second.reason, "bundle_invalid")
        self.assertEqual(self.destination.candidates(action_digest(self.action)), [])

    def test_receipt_producer_operation_and_limits_are_local_policy(self):
        untrusted_receipt = import_from_peer(
            self.action, self.catalog, self.config(receipt_public_keys={}),
            self.destination, now=self.now,
        )
        self.assertEqual(untrusted_receipt.reason, "receipt_key_untrusted")
        denied_operation = import_from_peer(
            self.action, self.catalog, self.config(allowed_operations=frozenset({"other/1"})),
            self.destination, now=self.now,
        )
        self.assertEqual(denied_operation.reason, "operation_denied")
        oversized_transfer = import_from_peer(
            self.action, self.catalog, self.config(max_transfer_bytes=4),
            self.destination, now=self.now,
        )
        self.assertEqual(oversized_transfer.reason, "transfer_limit_exceeded")
        oversized_artifact = import_from_peer(
            self.action, self.catalog, self.config(max_artifact_bytes=4),
            self.destination, now=self.now,
        )
        self.assertEqual(oversized_artifact.reason, "artifact_limit_exceeded")

    def test_peer_configuration_rejects_misbinding_and_accepts_zero_clock_skew(self):
        strict = self.config(max_future_clock_skew_seconds=0)
        self.assertEqual(strict.max_future_clock_skew_seconds, 0)
        with self.assertRaisesRegex(ValueError, "receipt public key mapping"):
            self.config(receipt_public_keys={"sha256:" + "0" * 64: self.receipt_public})

    def test_availability_entry_limit_is_enforced(self):
        second_action = echo_action("second")
        second_manifest, second_receipt = self.publish_result(second_action, b"second")
        self.catalog.publish(second_action, second_manifest, second_receipt, classification="public")
        outcome = import_from_peer(
            self.action, self.catalog, self.config(max_entries=1), self.destination, now=self.now
        )
        self.assertEqual(outcome.reason, "availability_limit_exceeded")

    def test_withdrawal_stops_new_distribution_and_lease_prunes_existing_copy(self):
        imported = import_from_peer(
            self.action, self.catalog, self.config(), self.destination, now=self.now
        )
        self.assertTrue(imported.hit)
        self.assertTrue(self.catalog.withdraw(self.result_digest))
        self.assertIsNone(self.catalog.fetch_bundle(self.result_digest))
        another = FederationCacheStore("another")
        after_withdrawal = import_from_peer(
            self.action, self.catalog, self.config(), another, now=self.now
        )
        self.assertEqual(after_withdrawal.reason, "not_available")
        self.assertEqual(len(self.destination.candidates(action_digest(self.action))), 1)
        self.current = self.now + timedelta(seconds=61)
        self.assertEqual(self.destination.prune(), 1)
        self.assertEqual(self.destination.candidates(action_digest(self.action)), [])
        self.assertEqual(self.destination._blobs, {})

    def test_imported_results_cannot_be_reexported(self):
        import_from_peer(self.action, self.catalog, self.config(), self.destination, now=self.now)
        with self.assertRaisesRegex(ValueError, "cannot be re-exported"):
            PublicPeerCatalog(
                "org-b", self.destination, bytes.fromhex("22" * 32),
                {self.receipt_key_id: self.receipt_public},
            )

    def test_durable_federation_cache_survives_process_boundary_and_prunes(self):
        with tempfile.TemporaryDirectory() as directory:
            durable = FilesystemFederationCacheStore(
                directory, "org-b-durable", clock=lambda: self.current
            )
            imported = import_from_peer(
                self.action, self.catalog, self.config(), durable, now=self.now
            )
            self.assertTrue(imported.hit)
            reopened = FilesystemFederationCacheStore(
                directory, "org-b-reopened", clock=lambda: self.current
            )
            self.assertEqual(reopened.candidates(action_digest(self.action)), [self.manifest])
            self.assertEqual(reopened.receipts(self.result_digest), [self.receipt])
            descriptor = self.manifest["artifacts"][0]
            self.assertEqual(reopened.get_blob(descriptor["digest"]), b"hello")
            self.assertEqual(reopened.summary(), {"entries": 1, "blobs": 1})
            with self.assertRaisesRegex(ValueError, "cannot be re-exported"):
                PublicPeerCatalog(
                    "org-b", reopened, bytes.fromhex("22" * 32),
                    {self.receipt_key_id: self.receipt_public},
                )
            self.current = self.now + timedelta(seconds=61)
            self.assertEqual(reopened.prune(), 1)
            self.assertEqual(reopened.summary(), {"entries": 0, "blobs": 0})

    def test_availability_signature_conformance_vector(self):
        vectors = json.loads(
            (ROOT / "conformance" / "availability-signatures-v0.json").read_text(encoding="utf-8")
        )
        for vector in vectors["vectors"]:
            with self.subTest(vector=vector["name"]):
                signed = sign_availability(
                    vector["unsigned_manifest"], bytes.fromhex(vector["private_seed_hex"])
                )
                self.assertEqual(signed, vector["signed_manifest"])
                self.assertTrue(
                    verify_availability(signed, signed["peer_id"], bytes.fromhex(vector["public_key_hex"]))
                )


if __name__ == "__main__":
    unittest.main()
