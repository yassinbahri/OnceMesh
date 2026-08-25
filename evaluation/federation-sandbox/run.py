from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from oncemesh import (  # noqa: E402
    MemoryStore,
    action_digest,
    digest_bytes,
    encode_public_key,
    manifest_digest,
    publish_signed_result,
    raw_public_key,
)
from oncemesh.canonical import canonical_json  # noqa: E402

RECEIPT_SEED = bytes.fromhex("77" * 32)
AVAILABILITY_SEED = bytes.fromhex("66" * 32)
RECEIVER_REQUEST_SEED = bytes.fromhex("88" * 32)
UNTRUSTED_REQUEST_SEED = bytes.fromhex("99" * 32)


def encoded(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(value) + b"\n")


def create_certificates(work: Path) -> None:
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "OnceMesh simulated pilot CA")])
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "origin")])
    server_certificate = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("origin")]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    ca_pem = ca_certificate.public_bytes(serialization.Encoding.PEM)
    server_pem = server_certificate.public_bytes(serialization.Encoding.PEM)
    server_key_pem = server_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    ca_key_pem = ca_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    (work / "origin" / "cert.pem").write_bytes(server_pem)
    (work / "receiver" / "ca.pem").write_bytes(ca_pem)
    (work / "untrusted" / "ca.pem").write_bytes(ca_pem)
    (work / "secrets" / "origin-tls-key.pem").write_bytes(server_key_pem)
    (work / "secrets" / "test-ca-key.pem").write_bytes(ca_key_pem)


def receiver_document(
    *, run_id: str, peer_id: str, evidence: str, cache: str, retention_seconds: int
) -> dict[str, Any]:
    return {
        "spec_version": "oncemesh.federation-pilot/v0",
        "role": "receiver",
        "run_id": run_id,
        "receiver_peer_id": peer_id,
        "request_private_seed_env": "ONCEMESH_REQUEST_SEED",
        "origin": {
            "base_url": "https://origin:8443",
            "peer_id": "org-a",
            "ca_file": "/pilot/ca.pem",
            "availability_public_key_base64url": encode_public_key(
                raw_public_key(AVAILABILITY_SEED)
            ),
            "receipt_public_keys": [{
                "key_id": digest_bytes(raw_public_key(RECEIPT_SEED)),
                "public_key_base64url": encode_public_key(raw_public_key(RECEIPT_SEED)),
            }],
            "trusted_producers": ["org-a:producer"],
            "allowed_operations": ["example.echo/1"],
        },
        "action_file": "/pilot/action.json",
        "evidence_file": f"/pilot/{evidence}",
        "cache_directory": f"/pilot/{cache}",
        "limits": {
            "timeout_milliseconds": 3000,
            "max_availability_response_bytes": 100000,
            "max_bundle_response_bytes": 100000,
            "max_entries": 100,
            "max_artifact_bytes": 1000,
            "max_transfer_bytes": 1000,
            "max_availability_age_seconds": 300,
            "max_future_clock_skew_seconds": 30,
            "retention_seconds": retention_seconds,
        },
    }


def prepare(work: Path) -> dict[str, Any]:
    for name in ("origin", "receiver", "untrusted", "secrets"):
        (work / name).mkdir(parents=True, exist_ok=False)
    for name, seed in (
        ("availability.seed", AVAILABILITY_SEED),
        ("receiver-request.seed", RECEIVER_REQUEST_SEED),
        ("untrusted-request.seed", UNTRUSTED_REQUEST_SEED),
        ("receipt.seed", RECEIPT_SEED),
    ):
        (work / "secrets" / name).write_text(encoded(seed) + "\n", encoding="ascii")
    create_certificates(work)

    now = datetime.now(timezone.utc)
    action = {
        "spec_version": "oncemesh.action/v0",
        "operation": {"name": "example.echo", "version": "1"},
        "inputs": {"text": "simulated three-role federation"},
        "executor": {"name": "sandbox-origin", "version": "1", "config": {}},
        "output_schema": "example.text/v1",
        "vary": {},
    }
    artifact = b"simulated three-role federation"
    store = MemoryStore("sandbox-preparation")
    manifest, receipt = publish_signed_result(
        store,
        action,
        {"result": (artifact, "text/plain")},
        producer="org-a:producer",
        produced_at=now,
        fresh_until=now + timedelta(hours=1),
        executor_environment={"implementation": "sandbox-origin"},
        private_key=RECEIPT_SEED,
    )
    receipt_public = raw_public_key(RECEIPT_SEED)
    receipt_identity = {
        "spec_version": "oncemesh.federation-identity/v0",
        "peer_id": "org-a",
        "purpose": "receipt",
        "profile": "oncemesh.ed25519/v1",
        "key_id": digest_bytes(receipt_public),
        "public_key_base64url": encode_public_key(receipt_public),
    }
    for directory in (work / "receiver", work / "untrusted"):
        write_json(directory / "action.json", action)
    write_json(work / "origin" / "action.json", action)
    write_json(work / "origin" / "result.json", manifest)
    write_json(work / "origin" / "receipt.json", receipt)
    write_json(work / "origin" / "receipt-identity.json", receipt_identity)
    (work / "origin" / "artifact.txt").write_bytes(artifact)

    origin = {
        "spec_version": "oncemesh.federation-pilot/v0",
        "role": "origin",
        "peer_id": "org-a",
        "listen": {"host": "0.0.0.0", "port": 8443},
        "tls": {
            "certificate_file": "/pilot/cert.pem",
            "private_key_file": "/run/secrets/origin_tls_key",
        },
        "availability_private_seed_env": "ONCEMESH_AVAILABILITY_SEED",
        "receipt_public_keys": [{
            "key_id": digest_bytes(receipt_public),
            "public_key_base64url": encode_public_key(receipt_public),
        }],
        "authorized_requesters": [{
            "peer_id": "org-b",
            "public_key_base64url": encode_public_key(raw_public_key(RECEIVER_REQUEST_SEED)),
        }],
        "publications": [{"file": "/pilot/publication.json"}],
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
    write_json(work / "origin" / "origin-initial.json", origin)
    write_json(
        work / "receiver" / "receiver-success.json",
        receiver_document(
            run_id="sandbox-success",
            peer_id="org-b",
            evidence="evidence-success.json",
            cache="cache",
            retention_seconds=30,
        ),
    )
    write_json(
        work / "receiver" / "receiver-after-withdrawal.json",
        receiver_document(
            run_id="sandbox-after-withdrawal",
            peer_id="org-b",
            evidence="evidence-after-withdrawal.json",
            cache="cache",
            retention_seconds=30,
        ),
    )
    write_json(
        work / "untrusted" / "untrusted.json",
        receiver_document(
            run_id="sandbox-untrusted",
            peer_id="org-c",
            evidence="evidence-untrusted.json",
            cache="cache",
            retention_seconds=2,
        ),
    )
    metadata = {
        "action_digest": action_digest(action),
        "result_digest": manifest_digest(manifest),
        "artifact_digest": digest_bytes(artifact),
        "artifact_bytes": len(artifact),
    }
    write_json(work / "metadata.json", metadata)
    return metadata


class Compose:
    def __init__(self, work: Path) -> None:
        self.work = work
        self.file = Path(__file__).resolve().parent / "compose.yaml"
        self.environment = os.environ.copy()
        self.environment["SANDBOX_WORK"] = work.as_posix()
        self.base = ["docker", "compose", "-f", str(self.file)]
        self.outputs: list[str] = []

    def run(self, arguments: list[str], *, expected: set[int] = {0}) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            self.base + arguments,
            cwd=ROOT,
            env=self.environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        self.outputs.extend([completed.stdout or "", completed.stderr or ""])
        if completed.returncode not in expected:
            raise RuntimeError(
                f"compose command failed ({completed.returncode}): {' '.join(arguments)}\n"
                f"{completed.stdout}\n{completed.stderr}"
            )
        return completed

    def secret_command(self, service: str, environment_name: str, secret_file: str, command: list[str], *, expected: set[int] = {0}) -> subprocess.CompletedProcess[str]:
        return self.run(
            ["run", "--rm", "--no-deps", service, environment_name, secret_file, "oncemesh-federation", *command],
            expected=expected,
        )

    def public_command(self, service: str, command: list[str], *, expected: set[int] = {0}) -> subprocess.CompletedProcess[str]:
        return self.run(
            ["run", "--rm", "--no-deps", "--entrypoint", "oncemesh-federation", service, *command],
            expected=expected,
        )

    def wait_ready(self, service: str) -> str:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            logs = self.run(["logs", "--no-color", service]).stdout
            if "oncemesh.federation-origin-ready/v0" in logs:
                return logs
            time.sleep(0.25)
        raise RuntimeError(f"{service} did not report readiness")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def secret_scan(work: Path, outputs: list[str]) -> dict[str, Any]:
    needles = [
        encoded(RECEIPT_SEED),
        encoded(AVAILABILITY_SEED),
        encoded(RECEIVER_REQUEST_SEED),
        encoded(UNTRUSTED_REQUEST_SEED),
        "OnceMesh-Signature",
    ]
    public_text = "\n".join(value for value in outputs if value is not None)
    for directory_name in ("origin", "receiver", "untrusted"):
        for path in (work / directory_name).rglob("*"):
            if path.is_file():
                try:
                    public_text += "\n" + path.read_text(encoding="utf-8")
                except UnicodeError:
                    public_text += "\n" + base64.b64encode(path.read_bytes()).decode("ascii")
    matches = [needle for needle in needles if needle in public_text]
    return {"scanned_needles": len(needles), "matches": len(matches), "passed": not matches}


def isolation_checks(compose_config: dict[str, Any]) -> dict[str, bool]:
    services = compose_config["services"]

    def secret_names(service: str) -> set[str]:
        values = services[service].get("secrets", [])
        return {
            item if isinstance(item, str) else item.get("source", "")
            for item in values
        }

    return {
        "private_network_is_internal": bool(compose_config["networks"]["federation"].get("internal")),
        "origin_has_no_host_ports": not services["origin_initial"].get("ports"),
        "roles_run_as_non_root": all(
            services[name].get("user") == "10001:10001"
            for name in ("origin_initial", "receiver", "untrusted_peer")
        ),
        "role_root_filesystems_are_read_only": all(
            services[name].get("read_only") is True
            for name in ("origin_initial", "receiver", "untrusted_peer")
        ),
        "origin_secrets_are_scoped": secret_names("origin_initial") == {"availability_seed", "origin_tls_key"},
        "receiver_secret_is_scoped": secret_names("receiver") == {"receiver_request_seed"},
        "untrusted_secret_is_scoped": secret_names("untrusted_peer") == {"untrusted_request_seed"},
        "linux_capabilities_are_dropped": all(
            services[name].get("cap_drop") == ["ALL"]
            for name in ("origin_initial", "receiver", "untrusted_peer")
        ),
    }


def execute(report_path: Path) -> dict[str, Any]:
    work = Path(tempfile.mkdtemp(prefix="oncemesh-m3-sim-")).resolve()
    if not work.name.startswith("oncemesh-m3-sim-") or work.parent != Path(tempfile.gettempdir()).resolve():
        raise RuntimeError("refusing unsafe sandbox workspace")
    compose = Compose(work)
    succeeded = False
    evidence: dict[str, Any] = {}
    try:
        metadata = prepare(work)
        compose.run(["build", "origin_initial"])
        compose.public_command(
            "origin_initial",
            [
                "package-publication",
                "--action", "/pilot/action.json",
                "--result-manifest", "/pilot/result.json",
                "--receipt", "/pilot/receipt.json",
                "--receipt-identity", "/pilot/receipt-identity.json",
                "--artifact", "result=/pilot/artifact.txt",
                "--classification", "public",
                "--confirm-publication-review",
                "--output", "/pilot/publication.json",
            ],
        )
        origin_preflight = json.loads(compose.secret_command(
            "origin_initial", "ONCEMESH_AVAILABILITY_SEED", "/run/secrets/availability_seed",
            ["preflight-origin", "--manifest", "/pilot/origin-initial.json"],
        ).stdout)
        receiver_preflight = json.loads(compose.secret_command(
            "receiver", "ONCEMESH_REQUEST_SEED", "/run/secrets/receiver_request_seed",
            ["preflight-receiver", "--manifest", "/pilot/receiver-success.json"],
        ).stdout)
        compose.run(["up", "-d", "origin_initial"])
        initial_logs = compose.wait_ready("origin_initial")
        success = json.loads(compose.secret_command(
            "receiver", "ONCEMESH_REQUEST_SEED", "/run/secrets/receiver_request_seed",
            ["probe", "--manifest", "/pilot/receiver-success.json"],
        ).stdout)
        untrusted_run = compose.secret_command(
            "untrusted_peer", "ONCEMESH_REQUEST_SEED", "/run/secrets/untrusted_request_seed",
            ["probe", "--manifest", "/pilot/untrusted.json"], expected={1},
        )
        untrusted = json.loads(untrusted_run.stdout)
        withdrawal = json.loads(compose.public_command(
            "origin_initial",
            [
                "withdraw-publication", "--manifest", "/pilot/origin-initial.json",
                "--result-digest", metadata["result_digest"],
                "--output", "/pilot/origin-withdrawn.json",
            ],
        ).stdout)
        compose.run(["stop", "origin_initial"])
        compose.run(["--profile", "withdrawn", "up", "-d", "origin_withdrawn"])
        withdrawn_logs = compose.wait_ready("origin_withdrawn")
        after_run = compose.secret_command(
            "receiver", "ONCEMESH_REQUEST_SEED", "/run/secrets/receiver_request_seed",
            ["probe", "--manifest", "/pilot/receiver-after-withdrawal.json"], expected={1},
        )
        after_withdrawal = json.loads(after_run.stdout)
        retain_until = datetime.fromisoformat(
            success["cache"]["retain_until"].replace("Z", "+00:00")
        )
        remaining_lease = (retain_until - datetime.now(timezone.utc)).total_seconds()
        if remaining_lease > 0:
            time.sleep(remaining_lease + 0.5)
        prune = json.loads(compose.public_command(
            "receiver",
            [
                "prune-cache", "--cache-directory", "/pilot/cache",
                "--evidence", "/pilot/evidence-prune.json",
            ],
        ).stdout)
        config = json.loads(compose.run(["config", "--format", "json"]).stdout)
        isolation = isolation_checks(config)
        scan = secret_scan(work, compose.outputs + [initial_logs, withdrawn_logs])
        image_id = compose.run(
            ["images", "--format", "json", "origin_initial"]
        ).stdout.strip()
        checks = {
            "origin_preflight_passed": origin_preflight["passed"],
            "receiver_preflight_passed": receiver_preflight["passed"],
            "tls_import_succeeded": success["outcome"]["hit"],
            "action_digest_preserved": success["action_digest"] == metadata["action_digest"],
            "result_digest_preserved": (
                success["advertised_result_digest"] == metadata["result_digest"]
                and success["imported_result_digest"] == metadata["result_digest"]
            ),
            "artifact_digest_preserved": (
                success["artifacts"][0]["digest"] == metadata["artifact_digest"]
                and success["artifacts"][0]["size"] == metadata["artifact_bytes"]
            ),
            "untrusted_peer_denied": (
                not untrusted["outcome"]["hit"]
                and untrusted["outcome"]["reason"] == "availability_invalid"
                and untrusted["artifacts"] == []
            ),
            "withdrawal_manifest_is_empty": withdrawal["remaining_publications"] == 0,
            "new_import_stopped_after_withdrawal": (
                not after_withdrawal["outcome"]["hit"]
                and after_withdrawal["outcome"]["reason"] == "not_available"
            ),
            "unexpired_receiver_copy_survived_withdrawal": after_withdrawal["cache"]["entries"] == 1,
            "real_lease_expiry_pruned_entry_and_blob": prune["passed"],
            "secret_scan_passed": scan["passed"],
            **isolation,
        }
        evidence = {
            "spec_version": "oncemesh.federation-simulated-acceptance-report/v0",
            "date": datetime.now(timezone.utc).date().isoformat(),
            "scenario_id": "m3-three-role-container-v0",
            "environment_kind": "simulated",
            "administrative_independence": False,
            "container_runtime": "Docker Desktop Linux containers",
            "image_reference": image_id,
            "metadata": metadata,
            "checks": checks,
            "secret_scan": scan,
            "passed": all(checks.values()),
            "limitations": [
                "One host operator controls every container, secret, network, and artifact.",
                "TLS uses an ephemeral private test CA rather than a managed certificate.",
                "Replay and rate-limit state remain local to one origin process.",
                "This report cannot satisfy independent organizational governance or key custody.",
            ],
        }
        if not evidence["passed"]:
            raise RuntimeError(f"simulated acceptance checks failed: {checks}")
        succeeded = True
    finally:
        try:
            compose.run(["--profile", "withdrawn", "down", "--remove-orphans"], expected={0})
        except Exception:
            pass
        shutil.rmtree(work)
    if not succeeded:
        raise RuntimeError("simulated acceptance did not complete")
    evidence["ephemeral_test_secrets_destroyed"] = not work.exists()
    if report_path.exists():
        raise ValueError("simulation report path already exists")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(canonical_json(evidence) + b"\n")
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--report",
        default=str(ROOT / "evaluation" / "results" / "federation-simulated-acceptance-20260824.json"),
    )
    args = parser.parse_args()
    report = execute(Path(args.report).resolve())
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
