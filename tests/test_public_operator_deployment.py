from __future__ import annotations

import json
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "public-operator"


class PublicOperatorDeploymentTests(unittest.TestCase):
    def test_compose_defaults_are_hardened_and_nonpublic(self) -> None:
        document = yaml.safe_load((DEPLOY / "compose.yaml").read_text(encoding="utf-8"))
        origin = document["services"]["origin"]

        self.assertTrue(origin["read_only"])
        self.assertEqual(origin["user"], "10001:10001")
        self.assertEqual(origin["cap_drop"], ["ALL"])
        self.assertIn("no-new-privileges:true", origin["security_opt"])
        self.assertEqual(origin["pids_limit"], 128)
        self.assertEqual(origin["mem_limit"], "512m")
        self.assertEqual(origin["cpus"], 1.0)
        self.assertEqual(
            origin["ports"],
            ["${ONCEMESH_BIND_ADDRESS:-127.0.0.1}:${ONCEMESH_PUBLIC_PORT:-8443}:8443"],
        )
        self.assertEqual(origin["secrets"], ["availability_seed", "tls_private_key"])
        self.assertTrue(all(volume["read_only"] for volume in origin["volumes"]))
        self.assertNotIn("privileged", origin)
        self.assertNotIn("network_mode", origin)

    def test_origin_template_uses_scoped_secrets_and_bounded_limits(self) -> None:
        manifest = json.loads((DEPLOY / "origin.json.template").read_text(encoding="utf-8"))

        self.assertEqual(manifest["listen"], {"host": "0.0.0.0", "port": 8443})
        self.assertEqual(manifest["tls"]["private_key_file"], "/run/secrets/tls_private_key")
        self.assertEqual(
            manifest["availability_private_seed_env"], "ONCEMESH_AVAILABILITY_SEED"
        )
        self.assertLessEqual(manifest["limits"]["max_concurrent_requests"], 16)
        self.assertLessEqual(manifest["limits"]["max_response_bytes"], 50_000_000)
        self.assertLessEqual(manifest["limits"]["max_requests_per_window"], 120)
        self.assertTrue(
            all(item["file"].startswith("/operator/publications/") for item in manifest["publications"])
        )

    def test_image_contains_no_operator_material_and_runs_nonroot(self) -> None:
        dockerfile = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("USER 10001:10001", dockerfile)
        self.assertIn('["python", "-m", "oncemesh.secret_exec"]', dockerfile)
        self.assertNotIn("availability.seed", dockerfile)
        self.assertNotIn("tls-private-key.pem", dockerfile)
        self.assertNotIn("COPY .", dockerfile)


if __name__ == "__main__":
    unittest.main()
