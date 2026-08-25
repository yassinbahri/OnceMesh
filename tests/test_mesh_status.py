from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncemesh.mesh_status import (  # noqa: E402
    generate_public_mesh_status,
    validate_public_mesh_status,
)


def directory_vector() -> dict:
    vectors = json.loads(
        (ROOT / "conformance" / "public-mesh-directory-v0.json").read_text(encoding="utf-8")
    )
    return vectors["valid_directory"]


class PublicMeshStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 25, 9, 0, 0, tzinfo=timezone.utc)

    def test_expected_unauthenticated_response_is_up(self) -> None:
        calls = []

        def probe(url: str, timeout: float) -> tuple[int, int]:
            calls.append((url, timeout))
            return 401, 83

        snapshot = generate_public_mesh_status(
            directory_vector(), probe=probe, clock=lambda: self.now
        )
        observation = snapshot["meshes"][0]
        self.assertEqual(observation["state"], "up")
        self.assertEqual(observation["response_time_ms"], 83)
        self.assertEqual(calls, [("https://mesh.example.com/v0/availability", 5.0)])
        validate_public_mesh_status(snapshot, directory_vector())

    def test_unexpected_http_response_is_degraded(self) -> None:
        snapshot = generate_public_mesh_status(
            directory_vector(),
            probe=lambda url, timeout: (503, 1200),
            clock=lambda: self.now,
        )
        self.assertEqual(snapshot["meshes"][0]["state"], "degraded")
        self.assertEqual(snapshot["meshes"][0]["http_status"], 503)

    def test_network_failure_is_down_without_leaking_details(self) -> None:
        def unavailable(url: str, timeout: float) -> tuple[int, int]:
            raise OSError("private diagnostic must not enter the snapshot")

        snapshot = generate_public_mesh_status(
            directory_vector(), probe=unavailable, clock=lambda: self.now
        )
        encoded = json.dumps(snapshot)
        self.assertEqual(snapshot["meshes"][0]["state"], "down")
        self.assertNotIn("private diagnostic", encoded)
        self.assertIsNone(snapshot["meshes"][0]["response_time_ms"])

    def test_inactive_registry_entry_is_not_probed(self) -> None:
        directory = directory_vector()
        directory["meshes"][0]["status"] = "suspended"

        def forbidden(url: str, timeout: float) -> tuple[int, int]:
            raise AssertionError("inactive entries must not be probed")

        snapshot = generate_public_mesh_status(
            directory, probe=forbidden, clock=lambda: self.now
        )
        self.assertEqual(snapshot["meshes"][0]["state"], "not_checked")
        self.assertIsNone(snapshot["meshes"][0]["checked_at"])

    def test_snapshot_must_match_directory_and_state_invariants(self) -> None:
        directory = directory_vector()
        snapshot = generate_public_mesh_status(
            directory,
            probe=lambda url, timeout: (200, 10),
            clock=lambda: self.now,
        )
        mismatched = deepcopy(snapshot)
        mismatched["meshes"][0]["peer_id"] = "different"
        with self.assertRaisesRegex(ValueError, "directory entry"):
            validate_public_mesh_status(mismatched, directory)

        inconsistent = deepcopy(snapshot)
        inconsistent["meshes"][0]["state"] = "down"
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            validate_public_mesh_status(inconsistent, directory)

        with self.assertRaisesRegex(ValueError, "concurrency"):
            generate_public_mesh_status(directory, concurrency=9)


if __name__ == "__main__":
    unittest.main()
