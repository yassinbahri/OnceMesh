from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import os
from pathlib import Path
import queue
import stat
import subprocess
import sys
import tempfile
import threading
import unittest

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncemesh import (  # noqa: E402
    FederationBundle,
    FilesystemFederationCacheStore,
    MemoryStore,
    digest_bytes,
    encode_public_key,
    manifest_digest,
    publish_signed_result,
    raw_public_key,
)
from oncemesh.federation_pilot import (  # noqa: E402
    build_origin_server,
    generate_federation_identity,
    load_origin_pilot,
    load_receiver_pilot,
    package_publication,
    preflight_origin,
    preflight_receiver,
    prune_receiver_cache,
    withdraw_origin_publication,
)


def echo_action():
    return {
        "spec_version": "oncemesh.action/v0",
        "operation": {"name": "example.echo", "version": "1"},
        "inputs": {"text": "separate process TLS pilot"},
        "executor": {"name": "example", "version": "1", "config": {}},
        "output_schema": "example.text/v1",
        "vary": {},
    }


class FederationPilotTests(unittest.TestCase):
    RECEIPT_SEED = bytes.fromhex("77" * 32)
    AVAILABILITY_SEED = bytes.fromhex("66" * 32)
    REQUEST_SEED = bytes.fromhex("88" * 32)

    @staticmethod
    def encoded(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    def create_fixture(self, directory):
        root = Path(directory)
        now = datetime.now(timezone.utc)
        action = echo_action()
        store = MemoryStore("pilot-fixture")
        manifest, receipt = publish_signed_result(
            store,
            action,
            {"result": (b"separate process TLS pilot", "text/plain")},
            producer="org-a:producer",
            produced_at=now,
            fresh_until=now + timedelta(hours=1),
            executor_environment={"implementation": "org-a-pilot-test"},
            private_key=self.RECEIPT_SEED,
        )
        receipt_public = raw_public_key(self.RECEIPT_SEED)
        receipt_key_id = digest_bytes(receipt_public)
        publication = {
            "spec_version": "oncemesh.federation-publication/v0",
            "classification": "public",
            "action": action,
            "manifest": manifest,
            "receipt": receipt,
            "artifacts": {"result": self.encoded(b"separate process TLS pilot")},
        }
        (root / "publication.json").write_text(json.dumps(publication), encoding="utf-8")
        (root / "action.json").write_text(json.dumps(action), encoding="utf-8")
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (root / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
        (root / "artifact.txt").write_bytes(b"separate process TLS pilot")
        receipt_identity = {
            "spec_version": "oncemesh.federation-identity/v0",
            "peer_id": "org-a",
            "purpose": "receipt",
            "profile": "oncemesh.ed25519/v1",
            "key_id": receipt_key_id,
            "public_key_base64url": encode_public_key(receipt_public),
        }
        (root / "receipt-identity.json").write_text(
            json.dumps(receipt_identity), encoding="utf-8"
        )

        tls_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(tls_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(
                x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                critical=False,
            )
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(tls_key, hashes.SHA256())
        )
        (root / "cert.pem").write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        (root / "key.pem").write_bytes(
            tls_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        origin = {
            "spec_version": "oncemesh.federation-pilot/v0",
            "role": "origin",
            "peer_id": "org-a",
            "listen": {"host": "127.0.0.1", "port": 0},
            "tls": {"certificate_file": "cert.pem", "private_key_file": "key.pem"},
            "availability_private_seed_env": "PILOT_AVAILABILITY_SEED",
            "receipt_public_keys": [{
                "key_id": receipt_key_id,
                "public_key_base64url": encode_public_key(receipt_public),
            }],
            "authorized_requesters": [{
                "peer_id": "org-b",
                "public_key_base64url": encode_public_key(raw_public_key(self.REQUEST_SEED)),
            }],
            "publications": [{"file": "publication.json"}],
            "limits": {
                "request_max_age_seconds": 60,
                "max_future_clock_skew_seconds": 5,
                "max_remembered_nonces": 100,
                "max_response_bytes": 100000,
                "max_concurrent_requests": 4,
                "max_requests_per_window": 20,
                "rate_window_seconds": 60,
            },
        }
        origin_path = root / "origin.json"
        origin_path.write_text(json.dumps(origin), encoding="utf-8")
        return {
            "root": root,
            "origin": origin,
            "origin_path": origin_path,
            "action": action,
            "manifest": manifest,
            "receipt_public": receipt_public,
            "receipt_key_id": receipt_key_id,
        }

    def test_key_generation_is_write_once_and_stdout_is_public_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private_path = root / "request.seed"
            public_path = root / "request.identity.json"
            seed = bytes.fromhex("aa" * 32)
            identity = generate_federation_identity(
                "org-b",
                "request",
                private_path,
                public_path,
                random_source=lambda size: seed,
            )
            secret = private_path.read_text(encoding="ascii").strip()
            public_text = public_path.read_text(encoding="utf-8")
            self.assertEqual(secret, self.encoded(seed))
            self.assertNotIn(secret, public_text)
            self.assertEqual(json.loads(public_text), identity)
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(private_path.stat().st_mode), 0o600)
            with self.assertRaisesRegex(ValueError, "must not already exist"):
                generate_federation_identity(
                    "org-b", "request", private_path, public_path
                )
            self.assertEqual(private_path.read_text(encoding="ascii").strip(), secret)

            cli_private = root / "availability.seed"
            cli_public = root / "availability.identity.json"
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(ROOT / "src")
            completed = subprocess.run(
                [
                    sys.executable, "-m", "oncemesh.federation_pilot", "keygen",
                    "--peer-id", "org-a", "--purpose", "availability",
                    "--private-seed-file", str(cli_private),
                    "--public-identity-file", str(cli_public),
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            generated_secret = cli_private.read_text(encoding="ascii").strip()
            self.assertNotIn(generated_secret, completed.stdout)
            self.assertEqual(json.loads(completed.stdout), json.loads(cli_public.read_text()))

    def test_publication_packager_requires_review_and_verifies_every_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.create_fixture(directory)
            root = fixture["root"]
            output = root / "packaged.json"
            arguments = (
                root / "action.json",
                root / "manifest.json",
                root / "receipt.json",
                root / "receipt-identity.json",
                {"result": root / "artifact.txt"},
                output,
            )
            with self.assertRaisesRegex(ValueError, "review confirmation"):
                package_publication(
                    *arguments, classification="public", publication_review_confirmed=False
                )
            self.assertFalse(output.exists())
            publication = package_publication(
                *arguments, classification="public", publication_review_confirmed=True
            )
            self.assertEqual(publication["classification"], "public")
            self.assertEqual(json.loads(output.read_text()), publication)
            with self.assertRaisesRegex(ValueError, "must not already exist"):
                package_publication(
                    *arguments, classification="public", publication_review_confirmed=True
                )

            (root / "artifact.txt").write_bytes(b"tampered")
            tampered_output = root / "tampered-package.json"
            tampered_arguments = (*arguments[:-1], tampered_output)
            with self.assertRaisesRegex(ValueError, "fails manifest integrity"):
                package_publication(
                    *tampered_arguments,
                    classification="public",
                    publication_review_confirmed=True,
                )
            self.assertFalse(tampered_output.exists())

    def test_preflight_reports_are_network_free_and_secret_free(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.create_fixture(directory)
            availability_secret = self.encoded(self.AVAILABILITY_SEED)
            request_secret = self.encoded(self.REQUEST_SEED)
            origin_config = load_origin_pilot(
                fixture["origin_path"], {"PILOT_AVAILABILITY_SEED": availability_secret}
            )
            origin_report = preflight_origin(origin_config)
            self.assertTrue(origin_report["passed"])
            self.assertEqual(origin_report["role"], "origin")
            self.assertNotIn(availability_secret, json.dumps(origin_report))

            receiver = self.receiver_document(fixture, "https://127.0.0.1:443")
            receiver_path = fixture["root"] / "receiver-preflight.json"
            receiver_path.write_text(json.dumps(receiver), encoding="utf-8")
            receiver_config = load_receiver_pilot(
                receiver_path, {"PILOT_REQUEST_SEED": request_secret}
            )
            receiver_report = preflight_receiver(receiver_config)
            self.assertTrue(receiver_report["passed"])
            self.assertEqual(receiver_report["role"], "receiver")
            self.assertTrue(receiver_report["evidence_path_is_new"])
            self.assertNotIn(request_secret, json.dumps(receiver_report))

    def test_withdrawal_manifest_and_durable_prune_are_write_once(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.create_fixture(directory)
            result_digest = manifest_digest(fixture["manifest"])
            withdrawn_path = fixture["root"] / "origin-withdrawn.json"
            withdrawal = withdraw_origin_publication(
                fixture["origin_path"], result_digest, withdrawn_path
            )
            self.assertEqual(withdrawal["remaining_publications"], 0)
            withdrawn_document = json.loads(withdrawn_path.read_text())
            self.assertEqual(withdrawn_document["publications"], [])
            withdrawn_config = load_origin_pilot(
                withdrawn_path,
                {"PILOT_AVAILABILITY_SEED": self.encoded(self.AVAILABILITY_SEED)},
            )
            self.assertEqual(preflight_origin(withdrawn_config)["publications"], [])
            with self.assertRaisesRegex(ValueError, "must not already exist"):
                withdraw_origin_publication(
                    fixture["origin_path"], result_digest, withdrawn_path
                )

            cache_path = fixture["root"] / "durable-cache"
            cache = FilesystemFederationCacheStore(cache_path)
            imported_at = datetime.now(timezone.utc)
            cache.import_bundle(
                FederationBundle(
                    fixture["manifest"],
                    json.loads((fixture["root"] / "receipt.json").read_text()),
                    {"result": b"separate process TLS pilot"},
                ),
                imported_at + timedelta(seconds=1),
            )
            prune_evidence = fixture["root"] / "prune-evidence.json"
            pruned = prune_receiver_cache(
                cache_path, prune_evidence, now=imported_at + timedelta(seconds=2)
            )
            self.assertTrue(pruned["passed"])
            self.assertEqual(pruned["before"], {"entries": 1, "blobs": 1})
            self.assertEqual(pruned["after"], {"entries": 0, "blobs": 0})
            self.assertEqual(json.loads(prune_evidence.read_text()), pruned)

    def receiver_document(self, fixture, base_url):
        return {
            "spec_version": "oncemesh.federation-pilot/v0",
            "role": "receiver",
            "run_id": "tls-two-process-1",
            "receiver_peer_id": "org-b",
            "request_private_seed_env": "PILOT_REQUEST_SEED",
            "origin": {
                "base_url": base_url,
                "peer_id": "org-a",
                "ca_file": "cert.pem",
                "availability_public_key_base64url": encode_public_key(
                    raw_public_key(self.AVAILABILITY_SEED)
                ),
                "receipt_public_keys": [{
                    "key_id": fixture["receipt_key_id"],
                    "public_key_base64url": encode_public_key(fixture["receipt_public"]),
                }],
                "trusted_producers": ["org-a:producer"],
                "allowed_operations": ["example.echo/1"],
            },
            "action_file": "action.json",
            "evidence_file": "evidence.json",
            "cache_directory": "federation-cache",
            "limits": {
                "timeout_milliseconds": 2000,
                "max_availability_response_bytes": 100000,
                "max_bundle_response_bytes": 100000,
                "max_entries": 100,
                "max_artifact_bytes": 1000,
                "max_transfer_bytes": 1000,
                "max_availability_age_seconds": 300,
                "max_future_clock_skew_seconds": 30,
                "retention_seconds": 60,
            },
        }

    def test_manifests_keep_seeds_external_and_validate_key_bindings(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.create_fixture(directory)
            environment = {"PILOT_AVAILABILITY_SEED": self.encoded(self.AVAILABILITY_SEED)}
            config = load_origin_pilot(fixture["origin_path"], environment)
            self.assertEqual(config.peer_id, "org-a")
            self.assertNotIn(self.encoded(self.AVAILABILITY_SEED), fixture["origin_path"].read_text())

            bad = dict(fixture["origin"])
            bad["receipt_public_keys"] = [{
                "key_id": "sha256:" + "0" * 64,
                "public_key_base64url": encode_public_key(fixture["receipt_public"]),
            }]
            bad_path = fixture["root"] / "bad-origin.json"
            bad_path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match"):
                load_origin_pilot(bad_path, environment)

    def test_non_public_publication_stops_origin_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.create_fixture(directory)
            publication_path = fixture["root"] / "publication.json"
            publication = json.loads(publication_path.read_text())
            publication["classification"] = "internal"
            publication_path.write_text(json.dumps(publication), encoding="utf-8")
            config = load_origin_pilot(
                fixture["origin_path"],
                {"PILOT_AVAILABILITY_SEED": self.encoded(self.AVAILABILITY_SEED)},
            )
            with self.assertRaisesRegex(ValueError, "explicitly public"):
                build_origin_server(config)

    def test_receiver_requires_https_new_evidence_path_and_external_seed(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.create_fixture(directory)
            receiver = self.receiver_document(fixture, "http://127.0.0.1:1")
            receiver_path = fixture["root"] / "receiver.json"
            receiver_path.write_text(json.dumps(receiver), encoding="utf-8")
            environment = {"PILOT_REQUEST_SEED": self.encoded(self.REQUEST_SEED)}
            with self.assertRaisesRegex(ValueError, "bare HTTPS"):
                load_receiver_pilot(receiver_path, environment)

            receiver["origin"]["base_url"] = "https://127.0.0.1:1"
            (fixture["root"] / "evidence.json").write_text("{}", encoding="utf-8")
            receiver_path.write_text(json.dumps(receiver), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "already exists"):
                load_receiver_pilot(receiver_path, environment)

    def test_separate_process_tls_pilot_writes_secret_free_exact_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.create_fixture(directory)
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(ROOT / "src")
            environment["PILOT_AVAILABILITY_SEED"] = self.encoded(self.AVAILABILITY_SEED)
            origin = subprocess.Popen(
                [sys.executable, "-m", "oncemesh.federation_pilot", "serve", "--manifest", str(fixture["origin_path"])],
                cwd=ROOT,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            lines = queue.Queue()

            def read_ready():
                lines.put(origin.stdout.readline() if origin.stdout else "")

            reader = threading.Thread(target=read_ready, daemon=True)
            reader.start()
            reader.join(timeout=10)
            try:
                if reader.is_alive():
                    self.fail("origin did not become ready")
                readiness_line = lines.get_nowait()
                if not readiness_line:
                    stderr = origin.stderr.read() if origin.stderr else ""
                    self.fail(f"origin exited before readiness: {stderr}")
                readiness = json.loads(readiness_line)
                self.assertTrue(readiness["tls"])
                receiver = self.receiver_document(fixture, readiness["base_url"])
                receiver_path = fixture["root"] / "receiver.json"
                receiver_path.write_text(json.dumps(receiver), encoding="utf-8")
                receiver_environment = environment.copy()
                receiver_environment["PILOT_REQUEST_SEED"] = self.encoded(self.REQUEST_SEED)
                completed = subprocess.run(
                    [sys.executable, "-m", "oncemesh.federation_pilot", "probe", "--manifest", str(receiver_path)],
                    cwd=ROOT,
                    env=receiver_environment,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                report = json.loads(completed.stdout)
                evidence_text = (fixture["root"] / "evidence.json").read_text(encoding="utf-8")
                evidence = json.loads(evidence_text)
                self.assertEqual(evidence, report)
                self.assertTrue(report["outcome"]["hit"])
                self.assertTrue(report["checks"]["tls_enabled"])
                self.assertTrue(report["checks"]["digests_preserved"])
                self.assertEqual(
                    report["advertised_result_digest"], manifest_digest(fixture["manifest"])
                )
                self.assertEqual(
                    report["imported_result_digest"], manifest_digest(fixture["manifest"])
                )
                self.assertNotIn(self.encoded(self.REQUEST_SEED), evidence_text)
                self.assertNotIn(self.encoded(self.AVAILABILITY_SEED), evidence_text)
                self.assertNotIn("OnceMesh-Signature", evidence_text)
                with self.assertRaisesRegex(ValueError, "already exists"):
                    load_receiver_pilot(receiver_path, receiver_environment)
            finally:
                origin.terminate()
                try:
                    origin.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    origin.kill()
                    origin.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
