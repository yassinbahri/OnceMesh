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
    FilesystemStore,
    MemoryStore,
    action_digest,
    manifest_digest,
    publish_signed_result,
    raw_public_key,
    receipt_digest,
    sign_receipt,
    validate_receipt,
    verify_receipt,
    verify_receipt_for_manifest,
)

PRIVATE_SEED = bytes.fromhex(
    "9d61b19deffd5a60ba844af492ec2cc4"
    "4449c5697b326919703bac031cae7f60"
)
PUBLIC_KEY = bytes.fromhex(
    "d75a980182b10ab7d54bfed3c964073a"
    "0ee172f3daa62325af021a68f707511a"
)


def manifest() -> dict:
    return {
        "spec_version": "oncemesh.result/v0",
        "action_digest": "sha256:" + "a" * 64,
        "artifacts": [],
        "produced_at": "2026-08-24T12:00:00Z",
        "fresh_until": "2026-08-25T12:00:00Z",
        "producer": "evaluation:local",
    }


def unsigned_receipt() -> dict:
    value = manifest()
    return {
        "spec_version": "oncemesh.receipt/v0",
        "result_digest": manifest_digest(value),
        "producer": value["producer"],
        "executor_environment": {
            "implementation": "oncemesh-python",
            "platform": "test/amd64",
        },
        "signature": None,
    }


class ReceiptSignatureTests(unittest.TestCase):
    def test_rfc8032_seed_derives_expected_public_key(self) -> None:
        self.assertEqual(raw_public_key(PRIVATE_SEED), PUBLIC_KEY)

    def test_sign_verify_and_manifest_binding(self) -> None:
        signed = sign_receipt(unsigned_receipt(), PRIVATE_SEED)
        self.assertTrue(verify_receipt(signed, PUBLIC_KEY))
        self.assertTrue(verify_receipt_for_manifest(signed, manifest(), PUBLIC_KEY))

        changed = manifest()
        changed["producer"] = "different"
        self.assertFalse(verify_receipt_for_manifest(signed, changed, PUBLIC_KEY))

    def test_tampering_fails_verification(self) -> None:
        signed = sign_receipt(unsigned_receipt(), PRIVATE_SEED)
        signed["executor_environment"]["platform"] = "tampered"
        self.assertFalse(verify_receipt(signed, PUBLIC_KEY))

    def test_wrong_key_id_fails_verification(self) -> None:
        signed = sign_receipt(unsigned_receipt(), PRIVATE_SEED)
        other = bytes.fromhex("1f" * 32)
        self.assertFalse(verify_receipt(signed, raw_public_key(other)))

    def test_noncanonical_or_unknown_fields_are_rejected(self) -> None:
        signed = sign_receipt(unsigned_receipt(), PRIVATE_SEED)
        signed["signature"]["value"] += "="
        with self.assertRaisesRegex(ValueError, "canonical base64url"):
            validate_receipt(signed)
        value = unsigned_receipt()
        value["unknown"] = True
        with self.assertRaisesRegex(ValueError, "fields"):
            validate_receipt(value)

    def test_signed_publication_persists_receipt_in_both_stores(self) -> None:
        action = {
            "spec_version": "oncemesh.action/v0",
            "operation": {"name": "example.echo", "version": "1"},
            "inputs": {"text": "hello"},
            "executor": {"name": "test", "version": "1", "config": {}},
            "output_schema": "example.text/v1",
            "vary": {},
        }
        now = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
        for store_factory in (
            lambda _: MemoryStore("memory"),
            lambda directory: FilesystemStore(Path(directory) / "store"),
        ):
            with self.subTest(store=store_factory.__name__), tempfile.TemporaryDirectory() as directory:
                store = store_factory(directory)
                result, receipt = publish_signed_result(
                    store,
                    action,
                    {"text": (b"hello", "text/plain")},
                    producer="evaluation:local",
                    produced_at=now,
                    fresh_until=now + timedelta(hours=1),
                    executor_environment={"implementation": "test"},
                    private_key=PRIVATE_SEED,
                )
                stored = store.receipts(manifest_digest(result))
                self.assertEqual(stored, [receipt])
                self.assertTrue(verify_receipt_for_manifest(stored[0], result, PUBLIC_KEY))

    def test_conformance_vector(self) -> None:
        vectors = json.loads(
            (ROOT / "conformance" / "receipt-signatures-v1.json").read_text(encoding="utf-8")
        )
        for vector in vectors["vectors"]:
            with self.subTest(vector=vector["name"]):
                signed = sign_receipt(vector["unsigned_receipt"], bytes.fromhex(vector["private_seed_hex"]))
                self.assertEqual(signed, vector["signed_receipt"])
                self.assertEqual(receipt_digest(signed), vector["receipt_digest"])
                self.assertTrue(verify_receipt(signed, bytes.fromhex(vector["public_key_hex"])))


if __name__ == "__main__":
    unittest.main()
