from __future__ import annotations

import sys
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncemesh import action_digest, derive_authorization_partition  # noqa: E402
from oncemesh.adapters import build_pdf_to_text_action  # noqa: E402


class AuthorizationPartitionTests(unittest.TestCase):
    KEY = bytes.fromhex("44" * 32)

    def test_scope_order_is_normalized(self) -> None:
        first = derive_authorization_partition("tenant-a", ["documents:read", "pdf:parse"], self.KEY)
        second = derive_authorization_partition("tenant-a", ["pdf:parse", "documents:read"], self.KEY)
        self.assertEqual(first, second)

    def test_tenant_scope_subject_and_key_change_partition(self) -> None:
        baseline = derive_authorization_partition("tenant-a", ["documents:read"], self.KEY)
        variants = {
            derive_authorization_partition("tenant-b", ["documents:read"], self.KEY),
            derive_authorization_partition("tenant-a", ["documents:write"], self.KEY),
            derive_authorization_partition(
                "tenant-a", ["documents:read"], self.KEY, subject_partition="finance"
            ),
            derive_authorization_partition("tenant-a", ["documents:read"], bytes.fromhex("55" * 32)),
        }
        self.assertNotIn(baseline, variants)
        self.assertEqual(len(variants), 4)

    def test_partition_changes_pdf_action_identity(self) -> None:
        pdf = b"%PDF-private"
        first = derive_authorization_partition("tenant-a", ["documents:read"], self.KEY)
        second = derive_authorization_partition("tenant-b", ["documents:read"], self.KEY)
        self.assertNotEqual(
            action_digest(build_pdf_to_text_action(pdf, authorization_partition=first)),
            action_digest(build_pdf_to_text_action(pdf, authorization_partition=second)),
        )

    def test_weak_key_duplicate_scopes_and_malformed_claims_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "32 bytes"):
            derive_authorization_partition("tenant-a", ["read"], b"short")
        with self.assertRaisesRegex(ValueError, "unique"):
            derive_authorization_partition("tenant-a", ["read", "read"], self.KEY)
        with self.assertRaisesRegex(ValueError, "tenant"):
            derive_authorization_partition("", ["read"], self.KEY)

    def test_conformance_vector(self) -> None:
        vectors = json.loads(
            (ROOT / "conformance" / "authorization-partitions-v1.json").read_text(encoding="utf-8")
        )
        for vector in vectors["vectors"]:
            claims = vector["claims"]
            with self.subTest(vector=vector["name"]):
                self.assertEqual(
                    derive_authorization_partition(
                        claims["tenant"],
                        claims["scopes"],
                        bytes.fromhex(vector["partition_key_hex"]),
                        subject_partition=claims["subject_partition"],
                    ),
                    vector["authorization_partition"],
                )


if __name__ == "__main__":
    unittest.main()
