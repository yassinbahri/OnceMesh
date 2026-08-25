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
    FilePolicyRegistry,
    InMemoryMetrics,
    MemoryStore,
    execute_http_with_policy,
    publish_result,
    validate_policy_document,
)
from oncemesh.adapters import (  # noqa: E402
    FetchResponse,
    build_http_fetch_action,
    response_to_artifacts,
)


class RuntimeTransport:
    def __init__(self, action: dict, *, conditional_status: int = 304, body: bytes = b"stable") -> None:
        self.action = action
        self.conditional_status = conditional_status
        self.body = body
        self.conditional_calls = 0
        self.full_calls = 0

    def response(self, status: int, body: bytes) -> FetchResponse:
        return FetchResponse(
            status,
            self.action["inputs"]["url"],
            {"Content-Type": "text/html", "ETag": '"v1"'},
            body,
        )

    def conditional_get(self, *args, **kwargs) -> FetchResponse:
        self.conditional_calls += 1
        return self.response(self.conditional_status, self.body if self.conditional_status == 200 else b"")

    def __call__(self, *args, **kwargs) -> FetchResponse:
        self.full_calls += 1
        return self.response(200, self.body)


class PolicyRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 24, 16, tzinfo=timezone.utc)
        self.action = build_http_fetch_action("https://example.com/")
        self.store = MemoryStore("organization")
        initial = FetchResponse(
            200,
            "https://example.com/",
            {"Content-Type": "text/html", "ETag": '"v1"'},
            b"stable",
        )
        publish_result(
            self.store,
            self.action,
            response_to_artifacts(self.action, initial),
            producer="cached-producer",
            produced_at=self.now - timedelta(hours=2),
            fresh_until=self.now - timedelta(hours=1),
        )

    @staticmethod
    def document(*, enabled: bool = True, tier: str = "organization") -> dict:
        return {
            "spec_version": "oncemesh.policy/v0",
            "enabled": enabled,
            "operations": {
                "http.fetch/1": {
                    "mode": "conditional-substitute",
                    "trusted_result_producers": ["cached-producer"],
                    "trusted_validation_producers": ["runtime-producer"],
                    "allowed_tiers": [tier],
                    "max_validation_ttl_seconds": 600,
                    "receipt_requirement": "optional",
                    "trusted_receipt_keys": [],
                    "authorization_partition": "public",
                    "max_stale_seconds": 0,
                }
            },
        }

    def write_policy(self, directory: str, document: dict | str) -> Path:
        path = Path(directory) / "policy.json"
        path.write_text(document if isinstance(document, str) else json.dumps(document), encoding="utf-8")
        return path

    def execute(self, registry, transport, metrics):
        return execute_http_with_policy(
            self.action,
            [self.store],
            transport,
            metrics,
            registry,
            publish_to=self.store,
            producer="runtime-producer",
            validation_ttl_seconds=3600,
            estimated_execution_cost=0.01,
            estimated_execution_time_ms=200.0,
            now=self.now,
        )

    def test_trusted_304_substitutes_without_full_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = FilePolicyRegistry(self.write_policy(directory, self.document()), environment={})
            transport = RuntimeTransport(self.action)
            metrics = InMemoryMetrics()
            outcome = self.execute(registry, transport, metrics)
            self.assertTrue(outcome.substituted)
            self.assertEqual((transport.conditional_calls, transport.full_calls), (1, 0))
            self.assertEqual(outcome.artifacts["body"], (b"stable", "text/html"))
            summary = metrics.summary()
            self.assertEqual(summary["substitutions"], 1)
            self.assertEqual(summary["decision_reasons"], {"conditional_304": 1})
            record = next(iter(self.store._validations.values()))[0]
            self.assertEqual(record["fresh_until"], "2026-08-24T16:10:00Z")

    def test_environment_kill_switch_executes_full_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = FilePolicyRegistry(
                self.write_policy(directory, self.document()),
                environment={"ONCEMESH_DISABLE_SUBSTITUTION": "TRUE"},
            )
            transport = RuntimeTransport(self.action)
            metrics = InMemoryMetrics()
            outcome = self.execute(registry, transport, metrics)
            self.assertFalse(outcome.substituted)
            self.assertEqual(outcome.decision_reason, "kill_switch")
            self.assertEqual((transport.conditional_calls, transport.full_calls), (0, 1))
            self.assertEqual(metrics.summary()["kill_switch_activations"], 1)

    def test_malformed_policy_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = FilePolicyRegistry(self.write_policy(directory, "{broken"), environment={})
            transport = RuntimeTransport(self.action)
            outcome = self.execute(registry, transport, InMemoryMetrics())
            self.assertFalse(outcome.substituted)
            self.assertEqual(outcome.decision_reason, "policy_error")
            self.assertEqual(transport.full_calls, 1)

    def test_denied_tier_executes_full_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = FilePolicyRegistry(
                self.write_policy(directory, self.document(tier="different-tier")), environment={}
            )
            transport = RuntimeTransport(self.action)
            outcome = self.execute(registry, transport, InMemoryMetrics())
            self.assertFalse(outcome.substituted)
            self.assertEqual(outcome.decision_reason, "tier_denied")
            self.assertEqual(transport.full_calls, 1)

    def test_source_change_returns_and_publishes_new_response(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = FilePolicyRegistry(self.write_policy(directory, self.document()), environment={})
            transport = RuntimeTransport(self.action, conditional_status=200, body=b"changed")
            outcome = self.execute(registry, transport, InMemoryMetrics())
            self.assertFalse(outcome.substituted)
            self.assertEqual(outcome.decision_reason, "source_changed")
            self.assertEqual(outcome.artifacts["body"], (b"changed", "text/html"))
            self.assertEqual((transport.conditional_calls, transport.full_calls), (1, 0))

    def test_policy_is_reloaded_and_can_disable_next_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_policy(directory, self.document())
            registry = FilePolicyRegistry(path, environment={})
            first_transport = RuntimeTransport(self.action)
            first = self.execute(registry, first_transport, InMemoryMetrics())
            self.assertTrue(first.substituted)

            path.write_text(json.dumps(self.document(enabled=False)), encoding="utf-8")
            second_transport = RuntimeTransport(self.action)
            second = self.execute(registry, second_transport, InMemoryMetrics())
            self.assertFalse(second.substituted)
            self.assertEqual(second.decision_reason, "policy_disabled")
            self.assertEqual((second_transport.conditional_calls, second_transport.full_calls), (0, 1))

    def test_required_receipts_cannot_be_silently_ignored_by_http_mode(self) -> None:
        document = self.document()
        operation = document["operations"]["http.fetch/1"]
        operation["receipt_requirement"] = "required"
        operation["trusted_receipt_keys"] = ["sha256:" + "0" * 64]
        with self.assertRaisesRegex(ValueError, "exact-substitute"):
            validate_policy_document(document)

    def test_required_authorization_partition_cannot_be_ignored_by_http_mode(self) -> None:
        document = self.document()
        document["operations"]["http.fetch/1"]["authorization_partition"] = "required"
        with self.assertRaisesRegex(ValueError, "exact-substitute"):
            validate_policy_document(document)

    def test_public_http_policy_rejects_partitioned_action_before_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = FilePolicyRegistry(self.write_policy(directory, self.document()), environment={})
            transport = RuntimeTransport(self.action)
            metrics = InMemoryMetrics()
            self.action["vary"] = {"authorization_partition": "hmac-sha256:" + "0" * 64}
            outcome = self.execute(registry, transport, metrics)
            self.assertEqual(outcome.decision_reason, "authorization_partition_forbidden")
            self.assertEqual((transport.conditional_calls, transport.full_calls), (0, 1))

    def test_stale_mode_and_window_must_be_configured_together(self) -> None:
        stale = self.document()
        operation = stale["operations"]["http.fetch/1"]
        operation["mode"] = "stale-while-revalidate"
        with self.assertRaisesRegex(ValueError, "positive max_stale_seconds"):
            validate_policy_document(stale)

        ordinary = self.document()
        ordinary["operations"]["http.fetch/1"]["max_stale_seconds"] = 60
        with self.assertRaisesRegex(ValueError, "positive max_stale_seconds"):
            validate_policy_document(ordinary)


if __name__ == "__main__":
    unittest.main()
