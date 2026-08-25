from __future__ import annotations

from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import ssl
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncemesh import (  # noqa: E402
    EMPTY_BODY_DIGEST,
    FederationCacheStore,
    FederationHTTPServer,
    FederationPeerConfig,
    FederationRequestAuthenticator,
    FederationRequestRateLimiter,
    HttpFederationPeer,
    MemoryStore,
    PublicPeerCatalog,
    action_digest,
    digest_bytes,
    import_from_peer,
    manifest_digest,
    publish_signed_result,
    raw_public_key,
    sign_federation_request,
    verify_federation_request,
)


def echo_action():
    return {
        "spec_version": "oncemesh.action/v0",
        "operation": {"name": "example.echo", "version": "1"},
        "inputs": {"text": "hello over HTTP"},
        "executor": {"name": "example", "version": "1", "config": {}},
        "output_schema": "example.text/v1",
        "vary": {},
    }


class FederationHTTPTests(unittest.TestCase):
    RECEIPT_SEED = bytes.fromhex("77" * 32)
    AVAILABILITY_SEED = bytes.fromhex("66" * 32)
    REQUEST_SEED = bytes.fromhex("88" * 32)

    def setUp(self):
        self.now = datetime(2026, 8, 24, 22, tzinfo=timezone.utc)
        self.origin = MemoryStore("org-a-origin")
        self.receipt_public = raw_public_key(self.RECEIPT_SEED)
        self.receipt_key_id = digest_bytes(self.receipt_public)
        self.action = echo_action()
        self.manifest, self.receipt = publish_signed_result(
            self.origin,
            self.action,
            {"result": (b"hello over HTTP", "text/plain")},
            producer="org-a:producer",
            produced_at=self.now,
            fresh_until=self.now + timedelta(hours=1),
            executor_environment={"implementation": "org-a-http-test"},
            private_key=self.RECEIPT_SEED,
        )
        self.catalog = PublicPeerCatalog(
            "org-a",
            self.origin,
            self.AVAILABILITY_SEED,
            {self.receipt_key_id: self.receipt_public},
        )
        self.result_digest = self.catalog.publish(
            self.action, self.manifest, self.receipt, classification="public"
        )
        self.request_public = raw_public_key(self.REQUEST_SEED)

    def authenticator(self, **overrides):
        values = {
            "max_age_seconds": 60,
            "max_future_clock_skew_seconds": 5,
            "max_remembered_nonces": 100,
            "clock": lambda: self.now,
        }
        values.update(overrides)
        return FederationRequestAuthenticator({"org-b": self.request_public}, **values)

    def peer(self, base_url, **overrides):
        values = {
            "allow_insecure_loopback": True,
            "clock": lambda: self.now,
            "timeout_seconds": 1,
            "max_availability_response_bytes": 100_000,
            "max_bundle_response_bytes": 100_000,
        }
        values.update(overrides)
        return HttpFederationPeer(base_url, "org-b", self.REQUEST_SEED, **values)

    def import_config(self):
        availability_public = raw_public_key(self.AVAILABILITY_SEED)
        return FederationPeerConfig(
            peer_id="org-a",
            availability_public_key=availability_public,
            receipt_public_keys={self.receipt_key_id: self.receipt_public},
            trusted_producers=frozenset({"org-a:producer"}),
            allowed_operations=frozenset({"example.echo/1"}),
            max_entries=100,
            max_artifact_bytes=1000,
            max_transfer_bytes=1000,
            retention_seconds=60,
        )

    def tls_contexts(self, directory):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
        current = datetime.now(timezone.utc)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(current - timedelta(minutes=1))
            .not_valid_after(current + timedelta(days=1))
            .add_extension(
                x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                critical=False,
            )
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256())
        )
        certificate_path = Path(directory) / "server-cert.pem"
        key_path = Path(directory) / "server-key.pem"
        certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(certificate_path, key_path)
        client_context = ssl.create_default_context(cafile=str(certificate_path))
        return server_context, client_context

    def test_request_signature_conformance_vector(self):
        document = json.loads(
            (ROOT / "conformance" / "federation-request-signatures-v0.json").read_text(
                encoding="utf-8"
            )
        )
        for vector in document["vectors"]:
            with self.subTest(vector=vector["name"]):
                signature = sign_federation_request(
                    vector["request"], bytes.fromhex(vector["private_seed_hex"])
                )
                self.assertEqual(signature["key_id"], vector["key_id"])
                self.assertEqual(signature["value"], vector["signature"])
                self.assertTrue(
                    verify_federation_request(
                        vector["request"], signature, bytes.fromhex(vector["public_key_hex"])
                    )
                )

    def test_network_peer_imports_exact_bundle(self):
        destination = FederationCacheStore("org-b-federation", clock=lambda: self.now)
        with FederationHTTPServer(
            self.catalog, self.authenticator(), clock=lambda: self.now
        ) as server:
            outcome = import_from_peer(
                self.action, self.peer(server.base_url), self.import_config(), destination,
                now=self.now,
            )
        self.assertTrue(outcome.hit)
        self.assertEqual(outcome.result_digest, manifest_digest(self.manifest))
        self.assertEqual(destination.candidates(action_digest(self.action)), [self.manifest])
        artifact = self.manifest["artifacts"][0]
        self.assertEqual(destination.get_blob(artifact["digest"]), b"hello over HTTP")

    def test_ca_verified_tls_exchange_and_untrusted_ca_failure(self):
        destination = FederationCacheStore("org-b-tls", clock=lambda: self.now)
        with tempfile.TemporaryDirectory() as directory:
            server_context, client_context = self.tls_contexts(directory)
            with FederationHTTPServer(
                self.catalog,
                self.authenticator(),
                clock=lambda: self.now,
                tls_context=server_context,
            ) as server:
                self.assertTrue(server.base_url.startswith("https://"))
                outcome = import_from_peer(
                    self.action,
                    self.peer(
                        server.base_url,
                        allow_insecure_loopback=False,
                        tls_context=client_context,
                    ),
                    self.import_config(),
                    destination,
                    now=self.now,
                )
                self.assertTrue(outcome.hit)
                untrusted = HttpFederationPeer(
                    server.base_url,
                    "org-b",
                    self.REQUEST_SEED,
                    clock=lambda: self.now,
                    timeout_seconds=1,
                )
                denied = import_from_peer(
                    self.action,
                    untrusted,
                    self.import_config(),
                    FederationCacheStore(),
                    now=self.now,
                )
                self.assertEqual(denied.reason, "availability_invalid")

    def test_unconfigured_requester_is_denied_without_catalog_data(self):
        with FederationHTTPServer(
            self.catalog, self.authenticator(), clock=lambda: self.now
        ) as server:
            stranger = HttpFederationPeer(
                server.base_url,
                "org-c",
                bytes.fromhex("99" * 32),
                allow_insecure_loopback=True,
                clock=lambda: self.now,
            )
            outcome = import_from_peer(
                self.action, stranger, self.import_config(), FederationCacheStore(), now=self.now
            )
        self.assertEqual(outcome.reason, "availability_invalid")

    def test_nonce_replay_and_capacity_fail_closed(self):
        nonces = iter(["00" * 16, "11" * 16])
        with FederationHTTPServer(
            self.catalog,
            self.authenticator(max_remembered_nonces=1),
            clock=lambda: self.now,
        ) as server:
            peer = self.peer(server.base_url, nonce_factory=lambda: next(nonces))
            self.assertEqual(peer.availability(self.now)["peer_id"], "org-a")
            with self.assertRaisesRegex(ValueError, "availability request failed"):
                peer.availability(self.now)

        with FederationHTTPServer(
            self.catalog, self.authenticator(), clock=lambda: self.now
        ) as server:
            replay = self.peer(server.base_url, nonce_factory=lambda: "22" * 16)
            replay.availability(self.now)
            with self.assertRaisesRegex(ValueError, "availability request failed"):
                replay.availability(self.now)

    def test_per_peer_rate_limit_fails_closed(self):
        limiter = FederationRequestRateLimiter(1, 60, clock=lambda: self.now)
        with FederationHTTPServer(
            self.catalog,
            self.authenticator(),
            clock=lambda: self.now,
            rate_limiter=limiter,
            max_concurrent_requests=1,
        ) as server:
            peer = self.peer(server.base_url)
            peer.availability(self.now)
            with self.assertRaisesRegex(ValueError, "availability request failed"):
                peer.availability(self.now)
        with self.assertRaisesRegex(ValueError, "max_concurrent_requests"):
            FederationHTTPServer(
                self.catalog, self.authenticator(), max_concurrent_requests=0
            )

    def test_signature_is_bound_to_exact_path(self):
        request_object = {
            "spec_version": "oncemesh.federation-request/v0",
            "peer_id": "org-b",
            "timestamp": "2026-08-24T22:00:00Z",
            "nonce": "33" * 16,
            "method": "GET",
            "path": "/v0/availability",
            "body_digest": EMPTY_BODY_DIGEST,
        }
        signature = sign_federation_request(request_object, self.REQUEST_SEED)
        headers = {
            "OnceMesh-Peer-ID": request_object["peer_id"],
            "OnceMesh-Timestamp": request_object["timestamp"],
            "OnceMesh-Nonce": request_object["nonce"],
            "OnceMesh-Key-ID": signature["key_id"],
            "OnceMesh-Signature": signature["value"],
        }
        with FederationHTTPServer(
            self.catalog, self.authenticator(), clock=lambda: self.now
        ) as server:
            target = server.base_url + "/v0/bundles/" + self.result_digest
            with self.assertRaises(HTTPError) as raised:
                urlopen(Request(target, headers=headers), timeout=1)
        self.assertEqual(raised.exception.code, 401)
        raised.exception.close()

    def test_stale_and_future_authenticated_requests_are_denied(self):
        with FederationHTTPServer(
            self.catalog, self.authenticator(), clock=lambda: self.now
        ) as server:
            stale = self.peer(server.base_url, clock=lambda: self.now - timedelta(seconds=61))
            future = self.peer(server.base_url, clock=lambda: self.now + timedelta(seconds=6))
            with self.assertRaises(ValueError):
                stale.availability()
            with self.assertRaises(ValueError):
                future.availability()

    def test_response_limit_and_https_default_are_enforced(self):
        with self.assertRaisesRegex(ValueError, "plain HTTP"):
            HttpFederationPeer("http://127.0.0.1:1", "org-b", self.REQUEST_SEED)
        with FederationHTTPServer(
            self.catalog, self.authenticator(), clock=lambda: self.now
        ) as server:
            bounded = self.peer(server.base_url, max_availability_response_bytes=10)
            with self.assertRaisesRegex(ValueError, "byte limit"):
                bounded.availability(self.now)
            bundle_bounded = self.peer(server.base_url, max_bundle_response_bytes=10)
            self.assertIsNone(bundle_bounded.fetch_bundle(self.result_digest))

    def test_redirect_is_not_followed(self):
        followed = []

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(inner):  # noqa: N802
                if inner.path == "/redirected":
                    followed.append(True)
                    inner.send_response(200)
                    inner.send_header("Content-Type", "application/json")
                    inner.send_header("Content-Length", "2")
                    inner.end_headers()
                    inner.wfile.write(b"{}")
                    return
                inner.send_response(302)
                inner.send_header("Location", "/redirected")
                inner.send_header("Content-Length", "0")
                inner.end_headers()

            def log_message(inner, format, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            peer = self.peer(f"http://127.0.0.1:{server.server_address[1]}")
            with self.assertRaisesRegex(ValueError, "availability request failed"):
                peer.availability(self.now)
            self.assertEqual(followed, [])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

    def test_timeout_is_reported_as_transport_failure(self):
        class SlowHandler(BaseHTTPRequestHandler):
            def do_GET(inner):  # noqa: N802
                time.sleep(0.2)
                body = b"{}"
                inner.send_response(200)
                inner.send_header("Content-Type", "application/json")
                inner.send_header("Content-Length", str(len(body)))
                inner.end_headers()
                try:
                    inner.wfile.write(body)
                except OSError:
                    pass

            def log_message(inner, format, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), SlowHandler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            peer = self.peer(
                f"http://127.0.0.1:{server.server_address[1]}", timeout_seconds=0.05
            )
            with self.assertRaisesRegex(ValueError, "availability request failed"):
                peer.availability(self.now)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
