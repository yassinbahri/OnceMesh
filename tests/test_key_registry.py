from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncemesh import FileReceiptKeyRegistry, digest_bytes, encode_public_key, raw_public_key, validate_key_registry  # noqa: E402

SEED_ONE = bytes.fromhex("11" * 32)
SEED_TWO = bytes.fromhex("22" * 32)


def entry(seed: bytes, *, status: str = "active", producer: str = "evaluation:local"):
    public = raw_public_key(seed)
    return digest_bytes(public), {
        "profile": "oncemesh.ed25519/v1",
        "public_key": encode_public_key(public),
        "status": status,
        "producers": [producer],
    }


class ReceiptKeyRegistryTests(unittest.TestCase):
    def test_rotation_overlap_accepts_both_active_keys(self) -> None:
        first_id, first = entry(SEED_ONE)
        second_id, second = entry(SEED_TWO)
        document = {"spec_version": "oncemesh.key-registry/v0", "keys": {first_id: first, second_id: second}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "keys.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            registry = FileReceiptKeyRegistry(path)
            self.assertEqual(registry.resolve(first_id, "evaluation:local").reason, "active")
            self.assertEqual(registry.resolve(second_id, "evaluation:local").reason, "active")

    def test_revocation_is_observed_on_next_resolution(self) -> None:
        key_id, value = entry(SEED_ONE)
        document = {"spec_version": "oncemesh.key-registry/v0", "keys": {key_id: value}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "keys.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            registry = FileReceiptKeyRegistry(path)
            self.assertEqual(registry.resolve(key_id, "evaluation:local").reason, "active")
            document["keys"][key_id]["status"] = "revoked"
            path.write_text(json.dumps(document), encoding="utf-8")
            self.assertEqual(registry.resolve(key_id, "evaluation:local").reason, "receipt_key_revoked")

    def test_unknown_key_and_producer_denial_fail_closed(self) -> None:
        key_id, value = entry(SEED_ONE)
        document = {"spec_version": "oncemesh.key-registry/v0", "keys": {key_id: value}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "keys.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            registry = FileReceiptKeyRegistry(path)
            self.assertEqual(registry.resolve("sha256:" + "0" * 64, "evaluation:local").reason, "receipt_key_unknown")
            self.assertEqual(registry.resolve(key_id, "different").reason, "receipt_producer_denied")

    def test_key_id_must_match_decoded_public_key(self) -> None:
        _, value = entry(SEED_ONE)
        document = {"spec_version": "oncemesh.key-registry/v0", "keys": {"sha256:" + "0" * 64: value}}
        with self.assertRaisesRegex(ValueError, "does not match"):
            validate_key_registry(document)


if __name__ == "__main__":
    unittest.main()
