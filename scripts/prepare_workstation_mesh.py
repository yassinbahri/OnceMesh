"""Prepare fresh, ignored runtime material for a workstation-hosted public pilot."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import ipaddress
import json
from pathlib import Path
import secrets
import sys
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncemesh import (  # noqa: E402
    MemoryStore,
    digest_bytes,
    encode_public_key,
    publish_signed_result,
    raw_public_key,
)
from oncemesh.canonical import canonical_json  # noqa: E402
from oncemesh.federation_pilot import package_publication  # noqa: E402


def _encoded(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(value) + b"\n")


def _create_certificates(public_root: Path, secret_root: Path) -> None:
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "OnceMesh workstation pilot CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.DNSName("origin"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    tls_root = public_root / "tls"
    tls_root.mkdir(parents=True)
    ca_pem = ca_cert.public_bytes(serialization.Encoding.PEM)
    server_pem = server_cert.public_bytes(serialization.Encoding.PEM)
    (tls_root / "ca.pem").write_bytes(ca_pem)
    (tls_root / "fullchain.pem").write_bytes(server_pem + ca_pem)
    (secret_root / "tls-private-key.pem").write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )


def prepare(output: Path) -> dict[str, Any]:
    if output.exists():
        raise ValueError(f"refusing to overwrite existing runtime: {output}")
    public_root = output / "public"
    secret_root = output / "secrets"
    source_root = output / "source"
    for path in (public_root, secret_root, source_root):
        path.mkdir(parents=True)

    availability_seed = secrets.token_bytes(32)
    receipt_seed = secrets.token_bytes(32)
    requester_seed = secrets.token_bytes(32)
    for name, seed in (
        ("availability.seed", availability_seed),
        ("receipt.seed", receipt_seed),
        ("requester.seed", requester_seed),
    ):
        (secret_root / name).write_text(_encoded(seed) + "\n", encoding="ascii")
    _create_certificates(public_root, secret_root)

    now = datetime.now(timezone.utc)
    action = {
        "spec_version": "oncemesh.action/v0",
        "operation": {"name": "example.echo", "version": "1"},
        "inputs": {"text": "OnceMesh workstation public canary"},
        "executor": {"name": "oncemesh-workstation-canary", "version": "1", "config": {}},
        "output_schema": "example.text/v1",
        "vary": {},
    }
    artifact = b"OnceMesh workstation public canary"
    manifest, receipt = publish_signed_result(
        MemoryStore("workstation-publication"),
        action,
        {"result": (artifact, "text/plain")},
        producer="oncemesh-workstation:canary",
        produced_at=now,
        fresh_until=now + timedelta(days=7),
        executor_environment={"implementation": "oncemesh-workstation-canary/1"},
        private_key=receipt_seed,
    )
    receipt_public = raw_public_key(receipt_seed)
    receipt_identity = {
        "spec_version": "oncemesh.federation-identity/v0",
        "peer_id": "oncemesh-workstation",
        "purpose": "receipt",
        "profile": "oncemesh.ed25519/v1",
        "key_id": digest_bytes(receipt_public),
        "public_key_base64url": encode_public_key(receipt_public),
    }
    _write_json(source_root / "action.json", action)
    _write_json(source_root / "manifest.json", manifest)
    _write_json(source_root / "receipt.json", receipt)
    _write_json(source_root / "receipt-identity.json", receipt_identity)
    (source_root / "artifact.txt").write_bytes(artifact)
    publication_path = public_root / "publications" / "canary.json"
    publication_path.parent.mkdir(parents=True)
    package_publication(
        source_root / "action.json",
        source_root / "manifest.json",
        source_root / "receipt.json",
        source_root / "receipt-identity.json",
        {"result": source_root / "artifact.txt"},
        publication_path,
        classification="public",
        publication_review_confirmed=True,
    )

    availability_public = raw_public_key(availability_seed)
    requester_public = raw_public_key(requester_seed)
    origin = {
        "spec_version": "oncemesh.federation-pilot/v0",
        "role": "origin",
        "peer_id": "oncemesh-workstation",
        "listen": {"host": "0.0.0.0", "port": 8443},
        "tls": {
            "certificate_file": "/operator/tls/fullchain.pem",
            "private_key_file": "/run/secrets/tls_private_key",
        },
        "availability_private_seed_env": "ONCEMESH_AVAILABILITY_SEED",
        "receipt_public_keys": [
            {
                "key_id": digest_bytes(receipt_public),
                "public_key_base64url": encode_public_key(receipt_public),
            }
        ],
        "authorized_requesters": [
            {
                "peer_id": "oncemesh-workstation-probe",
                "public_key_base64url": encode_public_key(requester_public),
            }
        ],
        "publications": [{"file": "/operator/publications/canary.json"}],
        "limits": {
            "request_max_age_seconds": 60,
            "max_future_clock_skew_seconds": 5,
            "max_remembered_nonces": 10000,
            "max_response_bytes": 50000000,
            "max_concurrent_requests": 16,
            "max_requests_per_window": 120,
            "rate_window_seconds": 60,
        },
    }
    _write_json(public_root / "origin.json", origin)
    summary = {
        "peer_id": "oncemesh-workstation",
        "producer": "oncemesh-workstation:canary",
        "operation": "example.echo/1",
        "availability_public_key_base64url": encode_public_key(availability_public),
        "receipt_key_id": digest_bytes(receipt_public),
        "receipt_public_key_base64url": encode_public_key(receipt_public),
        "requester_peer_id": "oncemesh-workstation-probe",
        "requester_public_key_base64url": encode_public_key(requester_public),
    }
    _write_json(output / "public-summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = prepare(args.output.resolve())
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
