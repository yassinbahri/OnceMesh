from __future__ import annotations

import json
from copy import deepcopy
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from oncemesh import (  # noqa: E402
    FilePolicyRegistry, FileReceiptKeyRegistry, InMemoryMetrics, MemoryStore,
    digest_bytes, encode_public_key, execute_deterministic_with_policy,
    publish_signed_result, raw_public_key,
    derive_authorization_partition,
)
from oncemesh.adapters import build_pdf_to_text_action, pdf_to_text_artifacts  # noqa: E402
from test_pdf_adapter import fixture_pdf  # noqa: E402


class DeterministicRuntimeTests(unittest.TestCase):
    PRIVATE_SEED = bytes.fromhex("33" * 32)

    def setUp(self) -> None:
        self.now = datetime(2026, 8, 24, 18, tzinfo=timezone.utc)
        self.pdf = fixture_pdf()
        self.action = build_pdf_to_text_action(self.pdf)
        self.store = MemoryStore("organization")
        self.manifest, self.receipt = publish_signed_result(
            self.store, self.action, pdf_to_text_artifacts(self.action, self.pdf),
            producer="evaluation:local", produced_at=self.now - timedelta(minutes=5),
            fresh_until=self.now + timedelta(hours=1),
            executor_environment={"implementation": "test"}, private_key=self.PRIVATE_SEED,
        )

    @property
    def key_id(self) -> str:
        return digest_bytes(raw_public_key(self.PRIVATE_SEED))

    def policy(self, mode="exact-substitute", tier="organization", receipt_requirement="optional", trusted_keys=None, authorization_partition="public"):
        return {
            "spec_version": "oncemesh.policy/v0", "enabled": True,
            "operations": {"document.pdf-to-text/1": {
                "mode": mode, "trusted_result_producers": ["evaluation:local"],
                "trusted_validation_producers": [], "allowed_tiers": [tier],
                "max_validation_ttl_seconds": 86400,
                "receipt_requirement": receipt_requirement,
                "trusted_receipt_keys": trusted_keys or [],
                "authorization_partition": authorization_partition,
                "max_stale_seconds": 0,
            }},
        }

    def key_registry(self, status="active"):
        public = raw_public_key(self.PRIVATE_SEED)
        return {"spec_version": "oncemesh.key-registry/v0", "keys": {self.key_id: {
            "profile": "oncemesh.ed25519/v1", "public_key": encode_public_key(public),
            "status": status, "producers": ["evaluation:local"],
        }}}

    def invoke(self, directory, document, environment=None, key_document=None, caller_partition=None):
        path = Path(directory) / "policy.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        key_registry = None
        if key_document is not None:
            key_path = Path(directory) / "keys.json"
            key_path.write_text(key_document if isinstance(key_document, str) else json.dumps(key_document), encoding="utf-8")
            key_registry = FileReceiptKeyRegistry(key_path)
        calls = 0

        def execute():
            nonlocal calls
            calls += 1
            return pdf_to_text_artifacts(self.action, self.pdf)

        metrics = InMemoryMetrics()
        outcome = execute_deterministic_with_policy(
            self.action, [self.store], execute, metrics,
            FilePolicyRegistry(path, environment=environment or {}),
            key_registry=key_registry, publish_to=self.store, producer="runtime:local",
            caller_authorization_partition=caller_partition,
            now=self.now, estimated_execution_time_ms=100.0,
        )
        return outcome, calls, metrics.summary()

    def test_exact_fresh_hit_substitutes_without_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            outcome, calls, summary = self.invoke(directory, self.policy())
            self.assertTrue(outcome.substituted)
            self.assertEqual(calls, 0)
            self.assertEqual(summary["decision_reasons"], {"exact_fresh_hit": 1})

    def test_denied_tier_fails_closed_to_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            outcome, calls, _ = self.invoke(directory, self.policy(tier="different"))
            self.assertEqual((outcome.decision_reason, calls), ("tier_denied", 1))

    def test_kill_switch_fails_closed_to_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            outcome, calls, summary = self.invoke(directory, self.policy(), {"ONCEMESH_DISABLE_SUBSTITUTION": "true"})
            self.assertEqual((outcome.decision_reason, calls), ("kill_switch", 1))
            self.assertEqual(summary["kill_switch_activations"], 1)

    def test_incompatible_mode_fails_closed_to_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            outcome, calls, _ = self.invoke(directory, self.policy(mode="conditional-substitute"))
            self.assertEqual((outcome.decision_reason, calls), ("policy_mode_incompatible", 1))

    def test_required_valid_receipt_substitutes(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = self.policy(receipt_requirement="required", trusted_keys=[self.key_id])
            outcome, calls, _ = self.invoke(directory, policy, key_document=self.key_registry())
            self.assertTrue(outcome.substituted)
            self.assertEqual(calls, 0)

    def test_required_receipt_without_registry_executes(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = self.policy(receipt_requirement="required", trusted_keys=[self.key_id])
            outcome, calls, _ = self.invoke(directory, policy)
            self.assertEqual((outcome.decision_reason, calls), ("receipt_registry_missing", 1))

    def test_revoked_receipt_key_executes(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = self.policy(receipt_requirement="required", trusted_keys=[self.key_id])
            outcome, calls, _ = self.invoke(directory, policy, key_document=self.key_registry("revoked"))
            self.assertEqual((outcome.decision_reason, calls), ("receipt_key_revoked", 1))

    def test_malformed_key_registry_executes(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = self.policy(receipt_requirement="required", trusted_keys=[self.key_id])
            outcome, calls, _ = self.invoke(directory, policy, key_document="{broken")
            self.assertEqual((outcome.decision_reason, calls), ("receipt_registry_error", 1))

    def test_unknown_receipt_key_executes(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = self.policy(receipt_requirement="required", trusted_keys=[self.key_id])
            empty_registry = {"spec_version": "oncemesh.key-registry/v0", "keys": {}}
            outcome, calls, _ = self.invoke(directory, policy, key_document=empty_registry)
            self.assertEqual((outcome.decision_reason, calls), ("receipt_key_unknown", 1))

    def test_policy_untrusted_receipt_key_executes(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = self.policy(receipt_requirement="required", trusted_keys=["sha256:" + "0" * 64])
            outcome, calls, _ = self.invoke(directory, policy, key_document=self.key_registry())
            self.assertEqual((outcome.decision_reason, calls), ("receipt_key_untrusted", 1))

    def test_tampered_receipt_executes(self):
        self.store._receipts.clear()
        tampered = deepcopy(self.receipt)
        tampered["executor_environment"]["implementation"] = "tampered"
        self.store.put_receipt(tampered)
        with tempfile.TemporaryDirectory() as directory:
            policy = self.policy(receipt_requirement="required", trusted_keys=[self.key_id])
            outcome, calls, _ = self.invoke(directory, policy, key_document=self.key_registry())
            self.assertEqual((outcome.decision_reason, calls), ("receipt_invalid", 1))

    def test_missing_required_receipt_executes(self):
        self.store._receipts.clear()
        with tempfile.TemporaryDirectory() as directory:
            policy = self.policy(receipt_requirement="required", trusted_keys=[self.key_id])
            outcome, calls, _ = self.invoke(directory, policy, key_document=self.key_registry())
            self.assertEqual((outcome.decision_reason, calls), ("receipt_missing", 1))

    def publish_private_action(self, partition):
        self.action = build_pdf_to_text_action(self.pdf, authorization_partition=partition)
        publish_signed_result(
            self.store, self.action, pdf_to_text_artifacts(self.action, self.pdf),
            producer="evaluation:local", produced_at=self.now - timedelta(minutes=2),
            fresh_until=self.now + timedelta(hours=1),
            executor_environment={"implementation": "test"}, private_key=self.PRIVATE_SEED,
        )

    def test_required_matching_authorization_partition_substitutes(self):
        partition = derive_authorization_partition("tenant-a", ["documents:read"], bytes.fromhex("44" * 32))
        self.publish_private_action(partition)
        with tempfile.TemporaryDirectory() as directory:
            policy = self.policy(authorization_partition="required")
            outcome, calls, _ = self.invoke(directory, policy, caller_partition=partition)
            self.assertTrue(outcome.substituted)
            self.assertEqual(calls, 0)

    def test_missing_or_mismatching_caller_partition_executes(self):
        partition = derive_authorization_partition("tenant-a", ["documents:read"], bytes.fromhex("44" * 32))
        other = derive_authorization_partition("tenant-b", ["documents:read"], bytes.fromhex("44" * 32))
        self.publish_private_action(partition)
        with tempfile.TemporaryDirectory() as directory:
            policy = self.policy(authorization_partition="required")
            missing, missing_calls, _ = self.invoke(directory, policy)
            mismatch, mismatch_calls, _ = self.invoke(directory, policy, caller_partition=other)
            self.assertEqual((missing.decision_reason, missing_calls), ("authorization_partition_missing", 1))
            self.assertEqual((mismatch.decision_reason, mismatch_calls), ("authorization_partition_mismatch", 1))

    def test_public_policy_forbids_partitioned_action(self):
        partition = derive_authorization_partition("tenant-a", ["documents:read"], bytes.fromhex("44" * 32))
        self.publish_private_action(partition)
        with tempfile.TemporaryDirectory() as directory:
            outcome, calls, _ = self.invoke(directory, self.policy(), caller_partition=partition)
            self.assertEqual((outcome.decision_reason, calls), ("authorization_partition_forbidden", 1))

    def test_cross_tenant_candidate_is_not_visible(self):
        key = bytes.fromhex("44" * 32)
        tenant_a = derive_authorization_partition("tenant-a", ["documents:read"], key)
        tenant_b = derive_authorization_partition("tenant-b", ["documents:read"], key)
        self.publish_private_action(tenant_a)
        self.action = build_pdf_to_text_action(self.pdf, authorization_partition=tenant_b)
        with tempfile.TemporaryDirectory() as directory:
            policy = self.policy(authorization_partition="required")
            outcome, calls, _ = self.invoke(directory, policy, caller_partition=tenant_b)
            self.assertEqual((outcome.decision_reason, calls), ("candidate_missing", 1))
            self.assertFalse(outcome.lookup.hit)


if __name__ == "__main__":
    unittest.main()
