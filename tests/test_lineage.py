from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncemesh import (  # noqa: E402
    FilesystemStore,
    MemoryStore,
    Policy,
    action_digest,
    candidate_for_revalidation,
    canonical_json,
    invalidation_digest,
    manifest_digest,
    publish_invalidation,
    publish_result,
    reuse,
    validate_invalidation,
    validate_manifest,
)


def action(name: str) -> dict:
    return {
        "spec_version": "oncemesh.action/v0",
        "operation": {"name": name, "version": "1"},
        "inputs": {"value": name},
        "executor": {"name": "lineage-test", "version": "1", "config": {}},
        "output_schema": "oncemesh.test/value-v1",
        "vary": {},
    }


class DerivedLineageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        self.store = MemoryStore("organization")
        self.source_action = action("source.fetch")
        self.derived_action = action("document.derive")

    def publish_source(self, *, fresh_for: timedelta = timedelta(hours=1)) -> dict:
        return publish_result(
            self.store,
            self.source_action,
            {"source": (b"source-v1", "application/octet-stream")},
            producer="source-producer",
            produced_at=self.now,
            fresh_until=self.now + fresh_for,
        )

    def publish_derived(self, source: dict, *, fresh_for: timedelta = timedelta(hours=2)) -> dict:
        return publish_result(
            self.store,
            self.derived_action,
            {"derived": (b"derived-v1", "application/octet-stream")},
            producer="derived-producer",
            produced_at=self.now,
            fresh_until=self.now + fresh_for,
            dependencies={"source": manifest_digest(source)},
        )

    @staticmethod
    def policy(now: datetime, **changes: object) -> Policy:
        values = {
            "now": now,
            "trusted_producers": frozenset({"source-producer", "derived-producer"}),
            "trusted_validation_producers": frozenset({"source-validator"}),
            "trusted_invalidation_producers": frozenset({"source-operator"}),
        }
        values.update(changes)
        return Policy(**values)

    def test_fresh_dependency_allows_derived_hit(self) -> None:
        source = self.publish_source()
        derived = self.publish_derived(source)

        outcome = reuse(self.derived_action, [self.store], self.policy(self.now))

        self.assertTrue(outcome.hit)
        self.assertEqual(outcome.manifest, derived)
        self.assertEqual(outcome.artifacts["derived"], b"derived-v1")

    def test_expired_dependency_rejects_otherwise_fresh_derived_result(self) -> None:
        source = self.publish_source(fresh_for=timedelta(minutes=30))
        self.publish_derived(source)

        outcome = reuse(
            self.derived_action,
            [self.store],
            self.policy(self.now + timedelta(hours=1)),
        )

        self.assertFalse(outcome.hit)
        self.assertEqual(outcome.rejections, ("organization:dependency_expired",))

    def test_trusted_validation_extends_unchanged_dependency(self) -> None:
        source = self.publish_source(fresh_for=timedelta(minutes=30))
        self.publish_derived(source)
        self.store.put_validation(
            {
                "spec_version": "oncemesh.validation/v0",
                "result_digest": manifest_digest(source),
                "validated_at": "2026-08-26T12:45:00Z",
                "fresh_until": "2026-08-26T14:00:00Z",
                "producer": "source-validator",
                "method": {
                    "name": "http.conditional",
                    "version": "1",
                    "status": 304,
                    "etag": "source-v1",
                    "last_modified": None,
                },
            }
        )

        outcome = reuse(
            self.derived_action,
            [self.store],
            self.policy(self.now + timedelta(hours=1)),
        )

        self.assertTrue(outcome.hit)

    def test_trusted_early_invalidation_cascades(self) -> None:
        source = self.publish_source()
        self.publish_derived(source)
        publish_invalidation(
            self.store,
            manifest_digest(source),
            producer="source-operator",
            invalidated_at=self.now + timedelta(minutes=10),
            reason="source.changed",
        )

        before = reuse(
            self.derived_action,
            [self.store],
            self.policy(self.now + timedelta(minutes=5)),
        )
        after = reuse(
            self.derived_action,
            [self.store],
            self.policy(self.now + timedelta(minutes=15)),
        )

        self.assertTrue(before.hit)
        self.assertFalse(after.hit)
        self.assertEqual(after.rejections, ("organization:dependency_invalidated",))

    def test_untrusted_invalidation_does_not_change_admissibility(self) -> None:
        source = self.publish_source()
        self.publish_derived(source)
        publish_invalidation(
            self.store,
            manifest_digest(source),
            producer="unknown",
            invalidated_at=self.now,
            reason="operator.manual",
        )

        outcome = reuse(self.derived_action, [self.store], self.policy(self.now))

        self.assertTrue(outcome.hit)

    def test_missing_dependency_fails_closed(self) -> None:
        publish_result(
            self.store,
            self.derived_action,
            {"derived": (b"value", "application/octet-stream")},
            producer="derived-producer",
            produced_at=self.now,
            fresh_until=self.now + timedelta(hours=1),
            dependencies={"source": "sha256:" + ("a" * 64)},
        )

        outcome = reuse(self.derived_action, [self.store], self.policy(self.now))

        self.assertFalse(outcome.hit)
        self.assertEqual(outcome.rejections, ("organization:dependency_missing",))

    def test_required_lineage_prevents_fallback_to_legacy_result(self) -> None:
        publish_result(
            self.store,
            self.derived_action,
            {"derived": (b"legacy", "application/octet-stream")},
            producer="derived-producer",
            produced_at=self.now - timedelta(minutes=1),
            fresh_until=self.now + timedelta(hours=1),
        )
        publish_result(
            self.store,
            self.derived_action,
            {"derived": (b"lineage", "application/octet-stream")},
            producer="derived-producer",
            produced_at=self.now,
            fresh_until=self.now + timedelta(hours=1),
            dependencies={"source": "sha256:" + ("a" * 64)},
        )

        outcome = reuse(
            self.derived_action,
            [self.store],
            self.policy(self.now, require_lineage=True),
        )

        self.assertFalse(outcome.hit)
        self.assertEqual(
            outcome.rejections,
            ("organization:dependency_missing", "organization:lineage_required"),
        )

    def test_dependency_count_and_depth_are_bounded(self) -> None:
        first = self.publish_source()
        second_action = action("derive.second")
        second = publish_result(
            self.store,
            second_action,
            {"second": (b"second", "application/octet-stream")},
            producer="derived-producer",
            produced_at=self.now,
            fresh_until=self.now + timedelta(hours=1),
            dependencies={"first": manifest_digest(first)},
        )
        self.publish_derived(second)

        depth_outcome = reuse(
            self.derived_action,
            [self.store],
            self.policy(self.now, max_dependency_depth=1),
        )
        count_outcome = reuse(
            self.derived_action,
            [self.store],
            self.policy(self.now, max_dependency_count=1),
        )

        self.assertFalse(depth_outcome.hit)
        self.assertIn("dependency_depth_exceeded", depth_outcome.rejections[0])
        self.assertFalse(count_outcome.hit)
        self.assertIn("dependency_count_exceeded", count_outcome.rejections[0])

    def test_malicious_cycle_fails_closed(self) -> None:
        root_digest = "sha256:" + ("b" * 64)
        dependency_digest = "sha256:" + ("a" * 64)
        root_manifest = {
            "spec_version": "oncemesh.result/v1",
            "action_digest": action_digest(self.derived_action),
            "artifacts": [],
            "produced_at": "2026-08-26T12:00:00Z",
            "fresh_until": "2026-08-26T13:00:00Z",
            "producer": "derived-producer",
            "dependencies": [{"name": "dependency", "result_digest": dependency_digest}],
        }
        dependency_manifest = {
            "spec_version": "oncemesh.result/v1",
            "action_digest": "sha256:" + ("c" * 64),
            "artifacts": [],
            "produced_at": "2026-08-26T12:00:00Z",
            "fresh_until": "2026-08-26T13:00:00Z",
            "producer": "source-producer",
            "dependencies": [{"name": "root", "result_digest": root_digest}],
        }

        class MaliciousCycleStore:
            name = "malicious"

            def candidates(self, requested_action_digest: str) -> list[dict]:
                return [root_manifest]

            def result(self, requested_result_digest: str) -> dict | None:
                return {
                    dependency_digest: dependency_manifest,
                    root_digest: root_manifest,
                }.get(requested_result_digest)

            def invalidations(self, requested_result_digest: str) -> list[dict]:
                return []

            def validations(self, requested_result_digest: str) -> list[dict]:
                return []

            def get_blob(self, requested_blob_digest: str) -> bytes | None:
                return None

        def fake_manifest_digest(value: dict) -> str:
            return root_digest if value is root_manifest else dependency_digest

        with patch("oncemesh.cache.manifest_digest", side_effect=fake_manifest_digest):
            outcome = reuse(
                self.derived_action,
                [MaliciousCycleStore()],
                self.policy(self.now, require_lineage=True),
            )

        self.assertFalse(outcome.hit)
        self.assertEqual(
            outcome.rejections,
            ("malicious:dependency_cycle",),
        )

    def test_revalidation_candidate_still_requires_admissible_dependencies(self) -> None:
        source = self.publish_source(fresh_for=timedelta(minutes=10))
        self.publish_derived(source, fresh_for=timedelta(minutes=10))

        outcome = candidate_for_revalidation(
            self.derived_action,
            [self.store],
            self.policy(self.now + timedelta(hours=1)),
        )

        self.assertFalse(outcome.hit)
        self.assertEqual(outcome.rejections, ("organization:dependency_expired",))

    def test_filesystem_store_resolves_dependency_by_result_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = FilesystemStore(directory, name="filesystem")
            source = publish_result(
                store,
                self.source_action,
                {"source": (b"source-v1", "application/octet-stream")},
                producer="source-producer",
                produced_at=self.now,
                fresh_until=self.now + timedelta(hours=1),
            )
            publish_result(
                store,
                self.derived_action,
                {"derived": (b"derived-v1", "application/octet-stream")},
                producer="derived-producer",
                produced_at=self.now,
                fresh_until=self.now + timedelta(hours=1),
                dependencies={"source": manifest_digest(source)},
            )

            reopened = FilesystemStore(directory, name="filesystem")
            outcome = reuse(self.derived_action, [reopened], self.policy(self.now))

            self.assertTrue(outcome.hit)

    def test_portable_manifest_and_invalidation_vector(self) -> None:
        document = json.loads(
            (ROOT / "conformance" / "derived-lineage-v0.json").read_text(encoding="utf-8")
        )
        vector = document["vectors"][0]

        validate_manifest(vector["manifest"])
        validate_invalidation(vector["invalidation"])
        self.assertEqual(
            canonical_json(vector["manifest"]).decode(), vector["manifest_canonical_json"]
        )
        self.assertEqual(manifest_digest(vector["manifest"]), vector["manifest_digest"])
        self.assertEqual(
            canonical_json(vector["invalidation"]).decode(),
            vector["invalidation_canonical_json"],
        )
        self.assertEqual(
            invalidation_digest(vector["invalidation"]), vector["invalidation_digest"]
        )


if __name__ == "__main__":
    unittest.main()
