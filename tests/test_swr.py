from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncemesh import (  # noqa: E402
    FilePolicyRegistry, InMemoryMetrics, MemoryStore, SingleFlightRevalidator,
    action_digest, execute_http_with_policy, manifest_digest, publish_result,
)
from oncemesh.adapters import FetchResponse, build_http_fetch_action, response_to_artifacts  # noqa: E402


class DeferredCoordinator:
    def __init__(self, *, fail_submit: bool = False) -> None:
        self.work = {}
        self.fail_submit = fail_submit

    def submit(self, key, work):
        if self.fail_submit:
            raise RuntimeError("scheduler unavailable")
        if key in self.work:
            return False
        self.work[key] = work
        return True

    def run(self, key):
        work = self.work.pop(key)
        work()


class SWRTransport:
    def __init__(self, action, *, conditional_status=304, changed_body=b"changed") -> None:
        self.action = action
        self.conditional_status = conditional_status
        self.changed_body = changed_body
        self.conditional_calls = 0
        self.full_calls = 0

    def _response(self, status, body):
        return FetchResponse(
            status, self.action["inputs"]["url"],
            {"Content-Type": "text/html", "ETag": '"v2"'}, body,
        )

    def conditional_get(self, *args, **kwargs):
        self.conditional_calls += 1
        body = self.changed_body if self.conditional_status == 200 else b""
        return self._response(self.conditional_status, body)

    def __call__(self, *args, **kwargs):
        self.full_calls += 1
        return self._response(200, b"synchronous")


class StaleWhileRevalidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 24, 20, tzinfo=timezone.utc)
        self.action = build_http_fetch_action("https://example.com/", accept="text/html")
        self.store = MemoryStore("organization")
        response = FetchResponse(
            200, "https://example.com/",
            {"Content-Type": "text/html", "ETag": '"v1"'}, b"stale",
        )
        self.manifest = publish_result(
            self.store, self.action, response_to_artifacts(self.action, response),
            producer="cached-producer", produced_at=self.now - timedelta(hours=1),
            fresh_until=self.now - timedelta(seconds=30),
        )

    @staticmethod
    def document(max_stale_seconds=120):
        return {
            "spec_version": "oncemesh.policy/v0", "enabled": True,
            "operations": {"http.fetch/1": {
                "mode": "stale-while-revalidate",
                "trusted_result_producers": ["cached-producer", "runtime-producer"],
                "trusted_validation_producers": ["runtime-producer"],
                "allowed_tiers": ["organization"],
                "max_validation_ttl_seconds": 60,
                "receipt_requirement": "optional", "trusted_receipt_keys": [],
                "authorization_partition": "public",
                "max_stale_seconds": max_stale_seconds,
            }},
        }

    def registry(self, directory, document=None):
        path = Path(directory) / "policy.json"
        path.write_text(json.dumps(document or self.document()), encoding="utf-8")
        return FilePolicyRegistry(path, environment={})

    def execute(self, registry, transport, metrics, coordinator=None):
        return execute_http_with_policy(
            self.action, [self.store], transport, metrics, registry,
            publish_to=self.store, producer="runtime-producer",
            validation_ttl_seconds=3600, now=self.now,
            revalidation_coordinator=coordinator,
        )

    def test_stale_returns_before_scheduled_304_then_records_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            coordinator = DeferredCoordinator()
            transport = SWRTransport(self.action)
            metrics = InMemoryMetrics()
            outcome = self.execute(self.registry(directory), transport, metrics, coordinator)
            self.assertTrue(outcome.substituted)
            self.assertEqual(outcome.artifacts["body"], (b"stale", "text/html"))
            self.assertEqual((transport.conditional_calls, transport.full_calls), (0, 0))
            coordinator.run(action_digest(self.action))
            self.assertEqual(transport.conditional_calls, 1)
            self.assertEqual(len(self.store.validations(manifest_digest(self.manifest))), 1)
            summary = metrics.summary()
            self.assertEqual(summary["background_revalidations_scheduled"], 1)
            self.assertEqual(summary["decision_reasons"]["background_not_modified"], 1)

    def test_concurrent_call_is_coalesced(self):
        with tempfile.TemporaryDirectory() as directory:
            coordinator = DeferredCoordinator()
            transport = SWRTransport(self.action)
            metrics = InMemoryMetrics()
            first = self.execute(self.registry(directory), transport, metrics, coordinator)
            second = self.execute(self.registry(directory), transport, metrics, coordinator)
            self.assertTrue(first.substituted and second.substituted)
            summary = metrics.summary()
            self.assertEqual(summary["background_revalidations_scheduled"], 1)
            self.assertEqual(summary["background_revalidations_coalesced"], 1)
            coordinator.run(action_digest(self.action))
            self.assertEqual(transport.conditional_calls, 1)

    def test_background_200_publishes_changed_result(self):
        with tempfile.TemporaryDirectory() as directory:
            coordinator = DeferredCoordinator()
            transport = SWRTransport(self.action, conditional_status=200)
            metrics = InMemoryMetrics()
            self.execute(self.registry(directory), transport, metrics, coordinator)
            coordinator.run(action_digest(self.action))
            candidates = self.store.candidates(action_digest(self.action))
            self.assertEqual(len(candidates), 2)
            self.assertEqual(metrics.summary()["decision_reasons"]["background_source_changed"], 1)

    def test_stale_window_exceeded_executes_synchronously(self):
        self.store = MemoryStore("organization")
        response = FetchResponse(200, "https://example.com/", {"Content-Type": "text/html", "ETag": '"v1"'}, b"old")
        publish_result(
            self.store, self.action, response_to_artifacts(self.action, response),
            producer="cached-producer", produced_at=self.now - timedelta(hours=2),
            fresh_until=self.now - timedelta(minutes=5),
        )
        with tempfile.TemporaryDirectory() as directory:
            transport = SWRTransport(self.action)
            outcome = self.execute(self.registry(directory), transport, InMemoryMetrics(), DeferredCoordinator())
            self.assertFalse(outcome.substituted)
            self.assertEqual(outcome.decision_reason, "stale_window_exceeded")
            self.assertEqual(transport.full_calls, 1)

    def test_missing_or_failed_scheduler_executes_synchronously(self):
        with tempfile.TemporaryDirectory() as directory:
            scenarios = (
                (None, "revalidation_scheduler_missing"),
                (DeferredCoordinator(fail_submit=True), "revalidation_schedule_failed"),
            )
            for coordinator, expected in scenarios:
                with self.subTest(expected=expected):
                    self.setUp()
                    transport = SWRTransport(self.action)
                    outcome = self.execute(
                        self.registry(directory), transport, InMemoryMetrics(), coordinator
                    )
                    self.assertEqual((outcome.decision_reason, transport.full_calls), (expected, 1))

    def test_latest_trusted_validation_controls_stale_age(self):
        self.store.put_validation({
            "spec_version": "oncemesh.validation/v0",
            "result_digest": manifest_digest(self.manifest),
            "validated_at": "2026-08-24T19:58:30Z",
            "fresh_until": "2026-08-24T19:59:30Z",
            "producer": "runtime-producer",
            "method": {"name": "http.conditional", "version": "1", "status": 304, "etag": '"v1"', "last_modified": None},
        })
        with tempfile.TemporaryDirectory() as directory:
            outcome = self.execute(
                self.registry(directory), SWRTransport(self.action), InMemoryMetrics(), DeferredCoordinator()
            )
            self.assertTrue(outcome.substituted)

    def test_background_failure_does_not_extend_freshness(self):
        with tempfile.TemporaryDirectory() as directory:
            coordinator = DeferredCoordinator()
            transport = SWRTransport(self.action, conditional_status=500)
            metrics = InMemoryMetrics()
            self.execute(self.registry(directory), transport, metrics, coordinator)
            coordinator.run(action_digest(self.action))
            self.assertEqual(self.store.validations(manifest_digest(self.manifest)), [])
            self.assertEqual(metrics.summary()["decision_reasons"]["background_failed"], 1)

    def test_untrusted_changed_result_producer_executes_synchronously(self):
        document = self.document()
        document["operations"]["http.fetch/1"]["trusted_result_producers"] = ["cached-producer"]
        with tempfile.TemporaryDirectory() as directory:
            transport = SWRTransport(self.action)
            outcome = self.execute(
                self.registry(directory, document), transport, InMemoryMetrics(), DeferredCoordinator()
            )
            self.assertEqual((outcome.decision_reason, transport.full_calls), ("refresh_producer_untrusted", 1))

    def test_fresh_candidate_needs_no_background_work(self):
        self.store = MemoryStore("organization")
        response = FetchResponse(200, "https://example.com/", {"Content-Type": "text/html", "ETag": '"v1"'}, b"fresh")
        publish_result(
            self.store, self.action, response_to_artifacts(self.action, response),
            producer="cached-producer", produced_at=self.now,
            fresh_until=self.now + timedelta(minutes=1),
        )
        with tempfile.TemporaryDirectory() as directory:
            coordinator = DeferredCoordinator()
            transport = SWRTransport(self.action)
            outcome = self.execute(self.registry(directory), transport, InMemoryMetrics(), coordinator)
            self.assertEqual(outcome.decision_reason, "fresh_hit")
            self.assertEqual(coordinator.work, {})
            self.assertEqual((transport.conditional_calls, transport.full_calls), (0, 0))

    def test_single_flight_releases_key_after_work(self):
        coordinator = SingleFlightRevalidator(max_workers=1)
        started = Event()
        release = Event()

        def work():
            started.set()
            release.wait(timeout=2)

        self.assertTrue(coordinator.submit("action", work))
        self.assertTrue(started.wait(timeout=2))
        self.assertFalse(coordinator.submit("action", lambda: None))
        release.set()
        self.assertTrue(coordinator.wait_for_idle(timeout=2))
        self.assertTrue(coordinator.submit("action", lambda: None))
        self.assertTrue(coordinator.wait_for_idle(timeout=2))
        coordinator.shutdown()


if __name__ == "__main__":
    unittest.main()
