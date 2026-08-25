from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncemesh import (  # noqa: E402
    CanonicalizationError,
    MemoryStore,
    Policy,
    action_digest,
    canonical_json,
    digest_bytes,
    publish_result,
    reuse,
)


def example_action() -> dict:
    return {
        "spec_version": "oncemesh.action/v0",
        "operation": {"name": "document.parse", "version": "1"},
        "inputs": {
            "content": {
                "digest": "sha256:" + ("a" * 64),
                "media_type": "text/html",
            }
        },
        "executor": {"name": "example-parser", "version": "2.1.0", "config": {}},
        "output_schema": "oncemesh.example/markdown-v1",
        "vary": {},
    }


class CanonicalizationTests(unittest.TestCase):
    def test_keys_are_sorted_and_utf8_is_preserved(self) -> None:
        self.assertEqual(canonical_json({"z": 1, "é": "ok", "a": True}), b'{"a":true,"z":1,"\xc3\xa9":"ok"}')

    def test_float_is_rejected(self) -> None:
        with self.assertRaises(CanonicalizationError):
            canonical_json({"temperature": 0.2})

    def test_unknown_action_field_is_rejected(self) -> None:
        action = example_action()
        action["scope"] = "public"
        with self.assertRaisesRegex(ValueError, "extra=\\['scope'\\]"):
            action_digest(action)

    def test_conformance_vectors(self) -> None:
        vectors = json.loads((ROOT / "conformance" / "action-digests-v0.json").read_text(encoding="utf-8"))
        for vector in vectors["vectors"]:
            with self.subTest(vector=vector["name"]):
                self.assertEqual(canonical_json(vector["action"]).decode(), vector["canonical_json"])
                self.assertEqual(action_digest(vector["action"]), vector["action_digest"])

    def test_generic_canonical_json_vectors(self) -> None:
        vectors = json.loads((ROOT / "conformance" / "canonical-json-v0.json").read_text(encoding="utf-8"))
        for vector in vectors["vectors"]:
            with self.subTest(vector=vector["name"]):
                encoded = canonical_json(vector["value"])
                self.assertEqual(encoded.decode(), vector["canonical_json"])
                self.assertEqual(digest_bytes(encoded), vector["digest"])

    def test_negative_canonicalization_vectors(self) -> None:
        vectors = json.loads((ROOT / "conformance" / "canonicalization-negative-v0.json").read_text(encoding="utf-8"))
        for vector in vectors["vectors"]:
            with self.subTest(vector=vector["name"]):
                with self.assertRaises(CanonicalizationError):
                    canonical_json(vector["value"])


class ReuseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
        self.action = example_action()
        self.store = MemoryStore("organization")

    def publish(self, *, producer: str = "team-a", expiry_delta: timedelta = timedelta(hours=1)) -> None:
        publish_result(
            self.store,
            self.action,
            {"document": (b"# Parsed\n", "text/markdown")},
            producer=producer,
            produced_at=self.now,
            fresh_until=self.now + expiry_delta,
        )

    def test_exact_fresh_trusted_result_is_reused(self) -> None:
        self.publish()
        outcome = reuse(
            self.action,
            [self.store],
            Policy(now=self.now, trusted_producers=frozenset({"team-a"})),
        )
        self.assertTrue(outcome.hit)
        self.assertEqual(outcome.tier, "organization")
        self.assertEqual(outcome.artifacts["document"], b"# Parsed\n")

    def test_expired_result_is_rejected_with_reason(self) -> None:
        self.publish(expiry_delta=timedelta(seconds=-1))
        outcome = reuse(self.action, [self.store], Policy(now=self.now))
        self.assertFalse(outcome.hit)
        self.assertEqual(outcome.rejections, ("organization:expired",))

    def test_untrusted_result_is_rejected(self) -> None:
        self.publish(producer="unknown")
        outcome = reuse(
            self.action,
            [self.store],
            Policy(now=self.now, trusted_producers=frozenset({"team-a"})),
        )
        self.assertFalse(outcome.hit)
        self.assertEqual(outcome.rejections, ("organization:untrusted_producer",))

    def test_naive_publish_timestamp_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            publish_result(
                self.store,
                self.action,
                {"document": (b"x", "text/plain")},
                producer="team-a",
                produced_at=datetime(2026, 8, 24, 12, 0),
                fresh_until=self.now + timedelta(hours=1),
            )

    def test_missing_artifact_is_rejected(self) -> None:
        self.publish()
        self.store._blobs.clear()  # simulate an incomplete or corrupt CAS
        outcome = reuse(self.action, [self.store], Policy(now=self.now))
        self.assertFalse(outcome.hit)
        self.assertEqual(outcome.rejections, ("organization:artifact_missing",))


if __name__ == "__main__":
    unittest.main()
