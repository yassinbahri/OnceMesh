from __future__ import annotations

import sys
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncemesh import (  # noqa: E402
    InMemoryMetrics,
    MemoryStore,
    Policy,
    manifest_digest,
    publish_result,
    reuse,
    run_conditional_http_shadow,
    canonical_json,
    validation_digest,
)
from oncemesh.adapters import (  # noqa: E402
    FetchResponse,
    build_http_fetch_action,
    response_to_artifacts,
)


class FakeConditionalTransport:
    def __init__(self, action: dict, *, conditional_status: int = 304, full_body: bytes = b"stable") -> None:
        self.action = action
        self.conditional_status = conditional_status
        self.full_body = full_body
        self.conditional_calls = 0
        self.full_calls = 0

    def _response(self, status: int, body: bytes) -> FetchResponse:
        return FetchResponse(
            status=status,
            final_url=self.action["inputs"]["url"],
            headers={"Content-Type": "text/html", "ETag": '"v1"'},
            body=body,
        )

    def conditional_get(self, *args, **kwargs) -> FetchResponse:
        self.conditional_calls += 1
        body = self.full_body if self.conditional_status == 200 else b""
        return self._response(self.conditional_status, body)

    def __call__(self, *args, **kwargs) -> FetchResponse:
        self.full_calls += 1
        return self._response(200, self.full_body)


class ConditionalValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 24, 15, tzinfo=timezone.utc)
        self.action = build_http_fetch_action("https://example.com/")
        self.store = MemoryStore("organization")
        initial = FetchResponse(
            status=200,
            final_url="https://example.com/",
            headers={"Content-Type": "text/html", "ETag": '"v1"'},
            body=b"stable",
        )
        self.manifest = publish_result(
            self.store,
            self.action,
            response_to_artifacts(self.action, initial),
            producer="team-a",
            produced_at=self.now - timedelta(hours=2),
            fresh_until=self.now - timedelta(hours=1),
        )

    def test_304_plus_full_match_records_validation_and_renews_freshness(self) -> None:
        transport = FakeConditionalTransport(self.action)
        metrics = InMemoryMetrics()
        outcome = run_conditional_http_shadow(
            self.action,
            [self.store],
            transport,
            metrics,
            policy=Policy(now=self.now, trusted_producers=frozenset({"team-a"})),
            publish_to=self.store,
            producer="team-a",
            fresh_until=self.now + timedelta(hours=1),
            now=self.now,
        )
        self.assertTrue(outcome.artifact_match)
        self.assertEqual((transport.conditional_calls, transport.full_calls), (1, 1))
        records = self.store.validations(manifest_digest(self.manifest))
        self.assertEqual(len(records), 1)
        renewed = reuse(
            self.action,
            [self.store],
            Policy(now=self.now, trusted_producers=frozenset({"team-a"})),
        )
        self.assertTrue(renewed.hit)
        self.assertIsNotNone(renewed.validation)
        self.assertEqual(metrics.summary()["validations_recorded"], 1)

    def test_304_with_mismatching_full_body_does_not_record_validation(self) -> None:
        transport = FakeConditionalTransport(self.action, full_body=b"changed")
        metrics = InMemoryMetrics()
        outcome = run_conditional_http_shadow(
            self.action,
            [self.store],
            transport,
            metrics,
            publish_to=self.store,
            producer="team-a",
            fresh_until=self.now + timedelta(hours=1),
            now=self.now,
        )
        self.assertFalse(outcome.artifact_match)
        self.assertEqual(self.store.validations(manifest_digest(self.manifest)), [])
        self.assertEqual(metrics.summary()["validations_recorded"], 0)

    def test_untrusted_validation_does_not_renew_result(self) -> None:
        self.store.put_validation(
            {
                "spec_version": "oncemesh.validation/v0",
                "result_digest": manifest_digest(self.manifest),
                "validated_at": "2026-08-24T15:00:00Z",
                "fresh_until": "2026-08-24T16:00:00Z",
                "producer": "unknown-validator",
                "method": {
                    "name": "http.conditional",
                    "version": "1",
                    "status": 304,
                    "etag": '"v1"',
                    "last_modified": None,
                },
            }
        )
        outcome = reuse(
            self.action,
            [self.store],
            Policy(now=self.now, trusted_producers=frozenset({"team-a"})),
        )
        self.assertFalse(outcome.hit)
        self.assertEqual(outcome.rejections, ("organization:expired",))

    def test_source_validation_conformance_vectors(self) -> None:
        vectors = json.loads(
            (ROOT / "conformance" / "source-validations-v0.json").read_text(encoding="utf-8")
        )
        for vector in vectors["vectors"]:
            with self.subTest(vector=vector["name"]):
                self.assertEqual(canonical_json(vector["record"]).decode(), vector["canonical_json"])
                self.assertEqual(validation_digest(vector["record"]), vector["validation_digest"])

    def test_validation_cannot_expire_before_it_was_observed(self) -> None:
        record = {
            "spec_version": "oncemesh.validation/v0",
            "result_digest": manifest_digest(self.manifest),
            "validated_at": "2026-08-24T15:00:00Z",
            "fresh_until": "2026-08-24T14:00:00Z",
            "producer": "team-a",
            "method": {
                "name": "http.conditional",
                "version": "1",
                "status": 304,
                "etag": "v1",
                "last_modified": None,
            },
        }
        with self.assertRaisesRegex(ValueError, "must not precede"):
            validation_digest(record)


if __name__ == "__main__":
    unittest.main()
