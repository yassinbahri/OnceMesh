"""Operator-facing commands for a separately administered federation pilot."""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import sys
import threading
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import urlsplit

from .canonical import DIGEST_PATTERN, action_digest, canonical_json, digest_bytes, manifest_digest, validate_action, validate_manifest
from .federation import (
    FederationPeerConfig,
    FilesystemFederationCacheStore,
    PublicPeerCatalog,
    import_from_peer,
)
from .federation_http import (
    FederationHTTPServer,
    FederationRequestAuthenticator,
    FederationRequestRateLimiter,
    HttpFederationPeer,
)
from .receipt import SIGNATURE_PROFILE, raw_public_key, validate_receipt, verify_receipt_for_manifest
from .store import MemoryStore

ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PUBLIC_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
IDENTITY_PURPOSES = frozenset({"availability", "request", "receipt"})


def _exact_keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{label} must contain exactly {sorted(expected)}")


def _strict_json(raw: str) -> Any:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON value {value} is unsupported")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)


def _load_document(path: Path) -> dict[str, Any]:
    try:
        value = _strict_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON document {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"JSON document {path} must be an object")
    return value


def _decode_32(value: Any, label: str) -> bytes:
    if not isinstance(value, str) or not PUBLIC_KEY_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must be canonical unpadded base64url")
    try:
        decoded = base64.b64decode(value + "=", altchars=b"-_", validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError(f"{label} is invalid base64url") from error
    if len(decoded) != 32 or base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
        raise ValueError(f"{label} must encode exactly 32 bytes")
    return decoded


def _decode_blob(value: Any, label: str) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]*", value) or len(value) % 4 == 1:
        raise ValueError(f"{label} must be canonical unpadded base64url")
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError(f"{label} is invalid base64url") from error
    if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
        raise ValueError(f"{label} is not canonical base64url")
    return decoded


def _seed_from_environment(name: Any, environment: Mapping[str, str]) -> bytes:
    if not isinstance(name, str) or not ENV_NAME_PATTERN.fullmatch(name):
        raise ValueError("private seed environment name is invalid")
    value = environment.get(name)
    if value is None:
        raise ValueError(f"required private seed environment variable {name} is missing")
    return _decode_32(value, f"environment variable {name}")


def _public_key_records(value: Any, label: str) -> dict[str, bytes]:
    if not isinstance(value, list) or not value or len(value) > 1000:
        raise ValueError(f"{label} must be a non-empty bounded array")
    result: dict[str, bytes] = {}
    for entry in value:
        _exact_keys(entry, {"key_id", "public_key_base64url"}, f"{label} entry")
        key_id = entry["key_id"]
        public_key = _decode_32(entry["public_key_base64url"], f"{label} public key")
        if not isinstance(key_id, str) or not DIGEST_PATTERN.fullmatch(key_id):
            raise ValueError(f"{label} key_id is invalid")
        if digest_bytes(public_key) != key_id:
            raise ValueError(f"{label} key_id does not match public key")
        if key_id in result:
            raise ValueError(f"{label} key identifiers must be unique")
        result[key_id] = public_key
    return result


def _string_set(value: Any, label: str, *, operation: bool = False) -> frozenset[str]:
    if (
        not isinstance(value, list) or not value or len(value) > 1000
        or any(not isinstance(item, str) or not item for item in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError(f"{label} must be a non-empty unique string array")
    if operation and any("/" not in item or item.startswith("/") or item.endswith("/") for item in value):
        raise ValueError("allowed operations must use non-empty name/version values")
    return frozenset(value)


def _bounded_integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{label} is outside the supported range")
    return value


def _relative(base: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(f"{label} path is invalid")
    selected = Path(value)
    return (selected if selected.is_absolute() else base / selected).resolve()


def _write_new(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def validate_federation_identity(document: dict[str, Any], *, purpose: str | None = None) -> bytes:
    _exact_keys(
        document,
        {"spec_version", "peer_id", "purpose", "profile", "key_id", "public_key_base64url"},
        "federation identity",
    )
    if document["spec_version"] != "oncemesh.federation-identity/v0":
        raise ValueError("unsupported federation identity version")
    if not isinstance(document["peer_id"], str) or not document["peer_id"]:
        raise ValueError("federation identity peer_id must not be empty")
    if document["purpose"] not in IDENTITY_PURPOSES or (purpose is not None and document["purpose"] != purpose):
        raise ValueError("federation identity purpose is invalid")
    if document["profile"] != SIGNATURE_PROFILE:
        raise ValueError("federation identity signature profile is invalid")
    public_key = _decode_32(document["public_key_base64url"], "identity public key")
    if document["key_id"] != digest_bytes(public_key):
        raise ValueError("federation identity key_id does not match public key")
    canonical_json(document)
    return public_key


def generate_federation_identity(
    peer_id: str,
    purpose: str,
    private_seed_file: str | Path,
    public_identity_file: str | Path,
    *,
    random_source: Any = secrets.token_bytes,
) -> dict[str, Any]:
    if not isinstance(peer_id, str) or not peer_id:
        raise ValueError("peer_id must not be empty")
    if purpose not in IDENTITY_PURPOSES:
        raise ValueError("identity purpose must be availability, request, or receipt")
    private_path = Path(private_seed_file).resolve()
    public_path = Path(public_identity_file).resolve()
    if private_path == public_path:
        raise ValueError("private and public identity paths must differ")
    if private_path.exists() or public_path.exists():
        raise ValueError("identity output paths must not already exist")
    seed = random_source(32)
    if not isinstance(seed, bytes) or len(seed) != 32:
        raise ValueError("random source must return exactly 32 bytes")
    public_key = raw_public_key(seed)
    identity = {
        "spec_version": "oncemesh.federation-identity/v0",
        "peer_id": peer_id,
        "purpose": purpose,
        "profile": SIGNATURE_PROFILE,
        "key_id": digest_bytes(public_key),
        "public_key_base64url": base64.urlsafe_b64encode(public_key).rstrip(b"=").decode("ascii"),
    }
    validate_federation_identity(identity, purpose=purpose)
    secret_text = base64.urlsafe_b64encode(seed).rstrip(b"=") + b"\n"
    _write_new(private_path, secret_text, 0o600)
    try:
        _write_new(public_path, canonical_json(identity) + b"\n", 0o644)
    except BaseException:
        try:
            private_path.unlink()
        except OSError:
            pass
        raise
    return identity


def package_publication(
    action_file: str | Path,
    manifest_file: str | Path,
    receipt_file: str | Path,
    receipt_identity_file: str | Path,
    artifact_files: Mapping[str, str | Path],
    output_file: str | Path,
    *,
    classification: str,
    publication_review_confirmed: bool,
) -> dict[str, Any]:
    if classification != "public" or not publication_review_confirmed:
        raise ValueError("public classification and publication review confirmation are required")
    output_path = Path(output_file).resolve()
    if output_path.exists():
        raise ValueError("publication output path must not already exist")
    action = _load_document(Path(action_file).resolve())
    manifest = _load_document(Path(manifest_file).resolve())
    receipt = _load_document(Path(receipt_file).resolve())
    identity = _load_document(Path(receipt_identity_file).resolve())
    public_key = validate_federation_identity(identity, purpose="receipt")
    validate_action(action)
    validate_manifest(manifest)
    validate_receipt(receipt, require_signature=True)
    if manifest["action_digest"] != action_digest(action):
        raise ValueError("publication action does not match result manifest")
    if not verify_receipt_for_manifest(receipt, manifest, public_key):
        raise ValueError("publication receipt signature or binding is invalid")
    expected_names = {item["name"] for item in manifest["artifacts"]}
    if set(artifact_files) != expected_names:
        raise ValueError("publication artifact file names do not match manifest")
    artifacts: dict[str, str] = {}
    for descriptor in manifest["artifacts"]:
        try:
            blob = Path(artifact_files[descriptor["name"]]).resolve().read_bytes()
        except OSError as error:
            raise ValueError("publication artifact file cannot be read") from error
        if len(blob) != descriptor["size"] or digest_bytes(blob) != descriptor["digest"]:
            raise ValueError("publication artifact file fails manifest integrity")
        artifacts[descriptor["name"]] = base64.urlsafe_b64encode(blob).rstrip(b"=").decode("ascii")
    publication = {
        "spec_version": "oncemesh.federation-publication/v0",
        "classification": "public",
        "action": action,
        "manifest": manifest,
        "receipt": receipt,
        "artifacts": artifacts,
    }
    verification_store = MemoryStore("publication-packager")
    _load_publication_document(publication, verification_store)
    _write_new(output_path, canonical_json(publication) + b"\n", 0o644)
    return publication


def withdraw_origin_publication(
    origin_manifest_file: str | Path,
    result_digest: str,
    output_file: str | Path,
) -> dict[str, Any]:
    if not isinstance(result_digest, str) or not DIGEST_PATTERN.fullmatch(result_digest):
        raise ValueError("withdrawal result digest is invalid")
    source_path = Path(origin_manifest_file).resolve()
    output_path = Path(output_file).resolve()
    if output_path.parent != source_path.parent:
        raise ValueError("withdrawn manifest output must remain beside the source manifest")
    if output_path.exists():
        raise ValueError("withdrawn manifest output must not already exist")
    document = _load_document(source_path)
    _exact_keys(
        document,
        {"spec_version", "role", "peer_id", "listen", "tls", "availability_private_seed_env", "receipt_public_keys", "authorized_requesters", "publications", "limits"},
        "origin pilot manifest",
    )
    if document["spec_version"] != "oncemesh.federation-pilot/v0" or document["role"] != "origin":
        raise ValueError("unsupported origin pilot manifest")
    retained = []
    removed = []
    for reference in document["publications"]:
        _exact_keys(reference, {"file"}, "publication reference")
        publication_path = _relative(source_path.parent, reference["file"], "publication")
        publication = _load_document(publication_path)
        _exact_keys(
            publication,
            {"spec_version", "classification", "action", "manifest", "receipt", "artifacts"},
            "federation publication",
        )
        validate_manifest(publication["manifest"])
        selected_digest = manifest_digest(publication["manifest"])
        if selected_digest == result_digest:
            removed.append(reference)
        else:
            retained.append(reference)
    if len(removed) != 1:
        raise ValueError("withdrawal must match exactly one configured publication")
    withdrawn = dict(document)
    withdrawn["publications"] = retained
    _write_new(output_path, canonical_json(withdrawn) + b"\n", 0o644)
    return {
        "spec_version": "oncemesh.federation-withdrawal-report/v0",
        "peer_id": document["peer_id"],
        "withdrawn_result_digest": result_digest,
        "remaining_publications": len(retained),
        "restart_required": True,
    }


def prune_receiver_cache(
    cache_directory: str | Path,
    evidence_file: str | Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    evidence_path = Path(evidence_file).resolve()
    if evidence_path.exists():
        raise ValueError("prune evidence path must not already exist")
    selected = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cache = FilesystemFederationCacheStore(cache_directory)
    before = cache.summary(prune=False)
    removed = cache.prune(selected)
    after = cache.summary(prune=False)
    report = {
        "spec_version": "oncemesh.federation-cache-prune-report/v0",
        "observed_at": selected.isoformat().replace("+00:00", "Z"),
        "before": before,
        "expired_entries_removed": removed,
        "after": after,
        "passed": removed > 0 and after["entries"] == 0 and after["blobs"] == 0,
    }
    _write_new(evidence_path, canonical_json(report) + b"\n", 0o644)
    return report


@dataclass(frozen=True)
class OriginPilotConfig:
    peer_id: str
    host: str
    port: int
    certificate_file: Path
    private_key_file: Path
    availability_seed: bytes
    receipt_public_keys: Mapping[str, bytes]
    authorized_requesters: Mapping[str, bytes]
    publication_files: tuple[Path, ...]
    request_max_age_seconds: int
    max_future_clock_skew_seconds: int
    max_remembered_nonces: int
    max_response_bytes: int
    max_concurrent_requests: int
    max_requests_per_window: int
    rate_window_seconds: int


@dataclass(frozen=True)
class ReceiverPilotConfig:
    run_id: str
    receiver_peer_id: str
    request_seed: bytes
    base_url: str
    origin_peer_id: str
    ca_file: Path
    availability_public_key: bytes
    receipt_public_keys: Mapping[str, bytes]
    trusted_producers: frozenset[str]
    allowed_operations: frozenset[str]
    action_file: Path
    evidence_file: Path
    cache_directory: Path
    limits: Mapping[str, int | float]


def load_origin_pilot(path: str | Path, environment: Mapping[str, str] | None = None) -> OriginPilotConfig:
    manifest_path = Path(path).resolve()
    document = _load_document(manifest_path)
    _exact_keys(
        document,
        {"spec_version", "role", "peer_id", "listen", "tls", "availability_private_seed_env", "receipt_public_keys", "authorized_requesters", "publications", "limits"},
        "origin pilot manifest",
    )
    if document["spec_version"] != "oncemesh.federation-pilot/v0" or document["role"] != "origin":
        raise ValueError("unsupported origin pilot manifest")
    if not isinstance(document["peer_id"], str) or not document["peer_id"]:
        raise ValueError("origin peer_id must not be empty")
    _exact_keys(document["listen"], {"host", "port"}, "origin listen")
    host = document["listen"]["host"]
    if not isinstance(host, str) or not host:
        raise ValueError("origin listen host must not be empty")
    port = _bounded_integer(document["listen"]["port"], "origin listen port", 0, 65535)
    _exact_keys(document["tls"], {"certificate_file", "private_key_file"}, "origin TLS")
    base = manifest_path.parent
    certificate_file = _relative(base, document["tls"]["certificate_file"], "certificate_file")
    private_key_file = _relative(base, document["tls"]["private_key_file"], "private_key_file")
    if not certificate_file.is_file() or not private_key_file.is_file():
        raise ValueError("origin TLS certificate and private key files must exist")
    requesters = document["authorized_requesters"]
    if not isinstance(requesters, list) or not requesters or len(requesters) > 1000:
        raise ValueError("authorized_requesters must be a non-empty bounded array")
    requester_keys: dict[str, bytes] = {}
    for entry in requesters:
        _exact_keys(entry, {"peer_id", "public_key_base64url"}, "authorized requester")
        peer_id = entry["peer_id"]
        if not isinstance(peer_id, str) or not peer_id or peer_id in requester_keys:
            raise ValueError("authorized requester peer identifiers must be non-empty and unique")
        requester_keys[peer_id] = _decode_32(entry["public_key_base64url"], "requester public key")
    publications = document["publications"]
    if not isinstance(publications, list) or len(publications) > 1000:
        raise ValueError("publications must be a bounded array")
    publication_files = []
    for entry in publications:
        _exact_keys(entry, {"file"}, "publication reference")
        publication_file = _relative(base, entry["file"], "publication")
        if not publication_file.is_file():
            raise ValueError("publication file must exist")
        publication_files.append(publication_file)
    _exact_keys(
        document["limits"],
        {"request_max_age_seconds", "max_future_clock_skew_seconds", "max_remembered_nonces", "max_response_bytes", "max_concurrent_requests", "max_requests_per_window", "rate_window_seconds"},
        "origin limits",
    )
    limits = document["limits"]
    return OriginPilotConfig(
        document["peer_id"],
        host,
        port,
        certificate_file,
        private_key_file,
        _seed_from_environment(document["availability_private_seed_env"], environment or os.environ),
        MappingProxyType(_public_key_records(document["receipt_public_keys"], "receipt_public_keys")),
        MappingProxyType(requester_keys),
        tuple(publication_files),
        _bounded_integer(limits["request_max_age_seconds"], "request_max_age_seconds", 1, 3600),
        _bounded_integer(limits["max_future_clock_skew_seconds"], "max_future_clock_skew_seconds", 0, 300),
        _bounded_integer(limits["max_remembered_nonces"], "max_remembered_nonces", 1, 1_000_000),
        _bounded_integer(limits["max_response_bytes"], "max_response_bytes", 1024, 1_000_000_000),
        _bounded_integer(limits["max_concurrent_requests"], "max_concurrent_requests", 1, 10_000),
        _bounded_integer(limits["max_requests_per_window"], "max_requests_per_window", 1, 1_000_000),
        _bounded_integer(limits["rate_window_seconds"], "rate_window_seconds", 1, 3600),
    )


def load_receiver_pilot(path: str | Path, environment: Mapping[str, str] | None = None) -> ReceiverPilotConfig:
    manifest_path = Path(path).resolve()
    document = _load_document(manifest_path)
    _exact_keys(
        document,
        {"spec_version", "role", "run_id", "receiver_peer_id", "request_private_seed_env", "origin", "action_file", "evidence_file", "cache_directory", "limits"},
        "receiver pilot manifest",
    )
    if document["spec_version"] != "oncemesh.federation-pilot/v0" or document["role"] != "receiver":
        raise ValueError("unsupported receiver pilot manifest")
    if not isinstance(document["run_id"], str) or not RUN_ID_PATTERN.fullmatch(document["run_id"]):
        raise ValueError("receiver run_id is invalid")
    if not isinstance(document["receiver_peer_id"], str) or not document["receiver_peer_id"]:
        raise ValueError("receiver peer_id must not be empty")
    origin = document["origin"]
    _exact_keys(
        origin,
        {"base_url", "peer_id", "ca_file", "availability_public_key_base64url", "receipt_public_keys", "trusted_producers", "allowed_operations"},
        "receiver origin",
    )
    parsed = urlsplit(origin["base_url"] if isinstance(origin["base_url"], str) else "")
    if (
        parsed.scheme != "https" or not parsed.hostname or parsed.path not in {"", "/"}
        or parsed.query or parsed.fragment or parsed.username is not None or parsed.password is not None
    ):
        raise ValueError("origin base_url must be a bare HTTPS origin")
    if not isinstance(origin["peer_id"], str) or not origin["peer_id"]:
        raise ValueError("origin peer_id must not be empty")
    base = manifest_path.parent
    ca_file = _relative(base, origin["ca_file"], "origin CA")
    action_file = _relative(base, document["action_file"], "action")
    evidence_file = _relative(base, document["evidence_file"], "evidence")
    cache_directory = _relative(base, document["cache_directory"], "cache_directory")
    if not ca_file.is_file() or not action_file.is_file():
        raise ValueError("origin CA and action files must exist")
    if evidence_file.exists():
        raise ValueError("evidence_file already exists; use a new run_id and path")
    limits = document["limits"]
    expected_limits = {
        "timeout_milliseconds", "max_availability_response_bytes", "max_bundle_response_bytes",
        "max_entries", "max_artifact_bytes", "max_transfer_bytes",
        "max_availability_age_seconds", "max_future_clock_skew_seconds", "retention_seconds",
    }
    _exact_keys(limits, expected_limits, "receiver limits")
    checked_limits: dict[str, int | float] = {
        "timeout_milliseconds": _bounded_integer(
            limits["timeout_milliseconds"], "timeout_milliseconds", 1, 60_000
        )
    }
    for name, minimum, maximum in (
        ("max_availability_response_bytes", 1, 1_000_000_000),
        ("max_bundle_response_bytes", 1, 1_000_000_000),
        ("max_entries", 1, 100_000),
        ("max_artifact_bytes", 1, 1_000_000_000),
        ("max_transfer_bytes", 1, 1_000_000_000),
        ("max_availability_age_seconds", 1, 86_400),
        ("max_future_clock_skew_seconds", 0, 3600),
        ("retention_seconds", 1, 31_536_000),
    ):
        checked_limits[name] = _bounded_integer(limits[name], name, minimum, maximum)
    return ReceiverPilotConfig(
        document["run_id"],
        document["receiver_peer_id"],
        _seed_from_environment(document["request_private_seed_env"], environment or os.environ),
        origin["base_url"].rstrip("/"),
        origin["peer_id"],
        ca_file,
        _decode_32(origin["availability_public_key_base64url"], "availability public key"),
        MappingProxyType(_public_key_records(origin["receipt_public_keys"], "receipt_public_keys")),
        _string_set(origin["trusted_producers"], "trusted_producers"),
        _string_set(origin["allowed_operations"], "allowed_operations", operation=True),
        action_file,
        evidence_file,
        cache_directory,
        MappingProxyType(checked_limits),
    )


def _load_publication_document(
    document: dict[str, Any], store: MemoryStore
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    _exact_keys(
        document,
        {"spec_version", "classification", "action", "manifest", "receipt", "artifacts"},
        "federation publication",
    )
    if document["spec_version"] != "oncemesh.federation-publication/v0" or document["classification"] != "public":
        raise ValueError("federation publication must be explicitly public")
    validate_action(document["action"])
    validate_manifest(document["manifest"])
    validate_receipt(document["receipt"], require_signature=True)
    if not isinstance(document["artifacts"], dict):
        raise ValueError("publication artifacts must be an object")
    expected = {item["name"] for item in document["manifest"]["artifacts"]}
    if set(document["artifacts"]) != expected:
        raise ValueError("publication artifact names do not match manifest")
    for descriptor in document["manifest"]["artifacts"]:
        blob = _decode_blob(document["artifacts"][descriptor["name"]], "publication artifact")
        if len(blob) != descriptor["size"] or digest_bytes(blob) != descriptor["digest"]:
            raise ValueError("publication artifact integrity check failed")
        store.put_blob(blob)
    return document["action"], document["manifest"], document["receipt"]


def _load_publication(path: Path, store: MemoryStore) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return _load_publication_document(_load_document(path), store)


def _prepare_origin_catalog(
    config: OriginPilotConfig,
) -> tuple[PublicPeerCatalog, list[dict[str, Any]]]:
    store = MemoryStore(f"{config.peer_id}-pilot-origin")
    catalog = PublicPeerCatalog(
        config.peer_id,
        store,
        config.availability_seed,
        config.receipt_public_keys,
    )
    summaries = []
    for publication_file in config.publication_files:
        action, manifest, receipt = _load_publication(publication_file, store)
        result_digest = catalog.publish(action, manifest, receipt, classification="public")
        summaries.append({
            "action_digest": action_digest(action),
            "result_digest": result_digest,
            "producer": manifest["producer"],
            "artifacts": [
                {"name": item["name"], "digest": item["digest"], "size": item["size"]}
                for item in manifest["artifacts"]
            ],
        })
    return catalog, summaries


def _origin_tls_context(config: OriginPilotConfig) -> ssl.SSLContext:
    tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls_context.minimum_version = ssl.TLSVersion.TLSv1_2
    tls_context.load_cert_chain(config.certificate_file, config.private_key_file)
    return tls_context


def build_origin_server(config: OriginPilotConfig) -> FederationHTTPServer:
    catalog, _ = _prepare_origin_catalog(config)
    authenticator = FederationRequestAuthenticator(
        config.authorized_requesters,
        max_age_seconds=config.request_max_age_seconds,
        max_future_clock_skew_seconds=config.max_future_clock_skew_seconds,
        max_remembered_nonces=config.max_remembered_nonces,
    )
    return FederationHTTPServer(
        catalog,
        authenticator,
        host=config.host,
        port=config.port,
        max_response_bytes=config.max_response_bytes,
        tls_context=_origin_tls_context(config),
        max_concurrent_requests=config.max_concurrent_requests,
        rate_limiter=FederationRequestRateLimiter(
            config.max_requests_per_window, config.rate_window_seconds
        ),
    )


def preflight_origin(config: OriginPilotConfig) -> dict[str, Any]:
    _, publications = _prepare_origin_catalog(config)
    _origin_tls_context(config)
    report = {
        "spec_version": "oncemesh.federation-preflight-report/v0",
        "role": "origin",
        "peer_id": config.peer_id,
        "tls_certificate_digest": digest_bytes(config.certificate_file.read_bytes()),
        "authorized_requesters": [
            {"peer_id": peer_id, "key_id": digest_bytes(public_key)}
            for peer_id, public_key in sorted(config.authorized_requesters.items())
        ],
        "availability_key_id": digest_bytes(raw_public_key(config.availability_seed)),
        "receipt_key_ids": sorted(config.receipt_public_keys),
        "publications": publications,
        "limits": {
            "request_max_age_seconds": config.request_max_age_seconds,
            "max_future_clock_skew_seconds": config.max_future_clock_skew_seconds,
            "max_remembered_nonces": config.max_remembered_nonces,
            "max_response_bytes": config.max_response_bytes,
            "max_concurrent_requests": config.max_concurrent_requests,
            "max_requests_per_window": config.max_requests_per_window,
            "rate_window_seconds": config.rate_window_seconds,
        },
        "passed": True,
    }
    canonical_json(report)
    return report


def preflight_receiver(config: ReceiverPilotConfig) -> dict[str, Any]:
    action = _load_document(config.action_file)
    validate_action(action)
    tls_context = ssl.create_default_context(cafile=str(config.ca_file))
    tls_context.minimum_version = ssl.TLSVersion.TLSv1_2
    FederationPeerConfig(
        peer_id=config.origin_peer_id,
        availability_public_key=config.availability_public_key,
        receipt_public_keys=config.receipt_public_keys,
        trusted_producers=config.trusted_producers,
        allowed_operations=config.allowed_operations,
        max_entries=int(config.limits["max_entries"]),
        max_artifact_bytes=int(config.limits["max_artifact_bytes"]),
        max_transfer_bytes=int(config.limits["max_transfer_bytes"]),
        max_availability_age_seconds=int(config.limits["max_availability_age_seconds"]),
        max_future_clock_skew_seconds=int(config.limits["max_future_clock_skew_seconds"]),
        retention_seconds=int(config.limits["retention_seconds"]),
    )
    HttpFederationPeer(
        config.base_url,
        config.receiver_peer_id,
        config.request_seed,
        timeout_seconds=int(config.limits["timeout_milliseconds"]) / 1000,
        max_availability_response_bytes=int(config.limits["max_availability_response_bytes"]),
        max_bundle_response_bytes=int(config.limits["max_bundle_response_bytes"]),
        tls_context=tls_context,
    )
    report = {
        "spec_version": "oncemesh.federation-preflight-report/v0",
        "role": "receiver",
        "peer_id": config.receiver_peer_id,
        "origin_peer_id": config.origin_peer_id,
        "origin_url": config.base_url,
        "ca_bundle_digest": digest_bytes(config.ca_file.read_bytes()),
        "request_key_id": digest_bytes(raw_public_key(config.request_seed)),
        "availability_key_id": digest_bytes(config.availability_public_key),
        "receipt_key_ids": sorted(config.receipt_public_keys),
        "trusted_producers": sorted(config.trusted_producers),
        "allowed_operations": sorted(config.allowed_operations),
        "action_digest": action_digest(action),
        "limits": dict(config.limits),
        "evidence_path_is_new": not config.evidence_file.exists(),
        "passed": True,
    }
    canonical_json(report)
    return report


def run_receiver_pilot(config: ReceiverPilotConfig, *, now: datetime | None = None) -> dict[str, Any]:
    observed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    action = _load_document(config.action_file)
    validate_action(action)
    tls_context = ssl.create_default_context(cafile=str(config.ca_file))
    tls_context.minimum_version = ssl.TLSVersion.TLSv1_2
    peer = HttpFederationPeer(
        config.base_url,
        config.receiver_peer_id,
        config.request_seed,
        timeout_seconds=int(config.limits["timeout_milliseconds"]) / 1000,
        max_availability_response_bytes=int(config.limits["max_availability_response_bytes"]),
        max_bundle_response_bytes=int(config.limits["max_bundle_response_bytes"]),
        tls_context=tls_context,
    )
    policy = FederationPeerConfig(
        peer_id=config.origin_peer_id,
        availability_public_key=config.availability_public_key,
        receipt_public_keys=config.receipt_public_keys,
        trusted_producers=config.trusted_producers,
        allowed_operations=config.allowed_operations,
        max_entries=int(config.limits["max_entries"]),
        max_artifact_bytes=int(config.limits["max_artifact_bytes"]),
        max_transfer_bytes=int(config.limits["max_transfer_bytes"]),
        max_availability_age_seconds=int(config.limits["max_availability_age_seconds"]),
        max_future_clock_skew_seconds=int(config.limits["max_future_clock_skew_seconds"]),
        retention_seconds=int(config.limits["retention_seconds"]),
    )
    destination = FilesystemFederationCacheStore(
        config.cache_directory, f"{config.receiver_peer_id}-pilot"
    )
    outcome = import_from_peer(action, peer, policy, destination, now=observed_at)
    artifacts: list[dict[str, Any]] = []
    digests_preserved = False
    imported_result_digest: str | None = None
    if outcome.hit and outcome.result_digest is not None:
        candidates = destination.candidates(action_digest(action))
        if candidates:
            imported = candidates[0]
            imported_result_digest = manifest_digest(imported)
            artifacts = [
                {"name": item["name"], "digest": item["digest"], "size": item["size"]}
                for item in imported["artifacts"]
            ]
            digests_preserved = (
                imported["action_digest"] == action_digest(action)
                and imported_result_digest == outcome.result_digest
                and all(
                    (blob := destination.get_blob(item["digest"])) is not None
                    and len(blob) == item["size"] and digest_bytes(blob) == item["digest"]
                    for item in imported["artifacts"]
                )
            )
    report = {
        "spec_version": "oncemesh.federation-pilot-report/v0",
        "run_id": config.run_id,
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "origin_peer_id": config.origin_peer_id,
        "receiver_peer_id": config.receiver_peer_id,
        "origin_url": config.base_url,
        "action_digest": action_digest(action),
        "advertised_result_digest": outcome.result_digest,
        "imported_result_digest": imported_result_digest,
        "artifacts": artifacts,
        "limits": dict(config.limits),
        "outcome": {"hit": outcome.hit, "reason": outcome.reason, "bytes_imported": outcome.bytes_imported},
        "cache": {
            "durable": True,
            **destination.summary(),
            "retain_until": (
                destination.lease_until(outcome.result_digest).isoformat().replace("+00:00", "Z")
                if outcome.result_digest is not None and destination.lease_until(outcome.result_digest) is not None
                else None
            ),
        },
        "checks": {
            "tls_enabled": config.base_url.startswith("https://"),
            "digests_preserved": digests_preserved,
            "local_policy_enforced": True,
        },
    }
    config.evidence_file.parent.mkdir(parents=True, exist_ok=True)
    with config.evidence_file.open("xb") as output:
        output.write(canonical_json(report) + b"\n")
        output.flush()
        os.fsync(output.fileno())
    return report


def serve_origin(config: OriginPilotConfig) -> None:
    server = build_origin_server(config)
    server.start()
    readiness = {
        "spec_version": "oncemesh.federation-origin-ready/v0",
        "peer_id": config.peer_id,
        "base_url": server.base_url,
        "tls": True,
        "publications": len(config.publication_files),
    }
    print(json.dumps(readiness, sort_keys=True), flush=True)
    stopped = threading.Event()
    try:
        while not stopped.wait(3600):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        server.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oncemesh-federation")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="serve reviewed public pilot publications over TLS")
    serve.add_argument("--manifest", required=True)
    probe = commands.add_parser("probe", help="import one exact action and write secret-free evidence")
    probe.add_argument("--manifest", required=True)
    keygen = commands.add_parser("keygen", help="create a write-once Ed25519 pilot identity")
    keygen.add_argument("--peer-id", required=True)
    keygen.add_argument("--purpose", required=True, choices=sorted(IDENTITY_PURPOSES))
    keygen.add_argument("--private-seed-file", required=True)
    keygen.add_argument("--public-identity-file", required=True)
    package = commands.add_parser(
        "package-publication", help="verify and package an explicitly public immutable result"
    )
    package.add_argument("--action", required=True)
    package.add_argument("--result-manifest", required=True)
    package.add_argument("--receipt", required=True)
    package.add_argument("--receipt-identity", required=True)
    package.add_argument("--artifact", action="append", required=True, metavar="NAME=PATH")
    package.add_argument("--output", required=True)
    package.add_argument("--classification", required=True, choices=["public"])
    package.add_argument("--confirm-publication-review", action="store_true")
    origin_preflight = commands.add_parser(
        "preflight-origin", help="verify origin material without contacting a peer"
    )
    origin_preflight.add_argument("--manifest", required=True)
    receiver_preflight = commands.add_parser(
        "preflight-receiver", help="verify receiver material without contacting a peer"
    )
    receiver_preflight.add_argument("--manifest", required=True)
    withdraw = commands.add_parser(
        "withdraw-publication", help="write a new origin manifest without one result"
    )
    withdraw.add_argument("--manifest", required=True)
    withdraw.add_argument("--result-digest", required=True)
    withdraw.add_argument("--output", required=True)
    prune = commands.add_parser(
        "prune-cache", help="remove receiver entries whose real retention lease expired"
    )
    prune.add_argument("--cache-directory", required=True)
    prune.add_argument("--evidence", required=True)
    return parser


def _artifact_arguments(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError("artifact arguments must use NAME=PATH")
        name, path = value.split("=", 1)
        if not name or not path or name in result:
            raise ValueError("artifact names and paths must be non-empty and unique")
        result[name] = Path(path)
    return result


def main() -> None:
    args = _parser().parse_args()
    try:
        if args.command == "serve":
            serve_origin(load_origin_pilot(args.manifest))
            return
        if args.command == "probe":
            report = run_receiver_pilot(load_receiver_pilot(args.manifest))
            print(json.dumps(report, indent=2, sort_keys=True))
            if not report["outcome"]["hit"]:
                raise SystemExit(1)
            return
        if args.command == "keygen":
            report = generate_federation_identity(
                args.peer_id,
                args.purpose,
                args.private_seed_file,
                args.public_identity_file,
            )
        elif args.command == "package-publication":
            publication = package_publication(
                args.action,
                args.result_manifest,
                args.receipt,
                args.receipt_identity,
                _artifact_arguments(args.artifact),
                args.output,
                classification=args.classification,
                publication_review_confirmed=args.confirm_publication_review,
            )
            report = {
                "spec_version": "oncemesh.federation-publication-created/v0",
                "action_digest": action_digest(publication["action"]),
                "result_digest": manifest_digest(publication["manifest"]),
                "artifacts": publication["manifest"]["artifacts"],
                "classification": "public",
            }
        elif args.command == "preflight-origin":
            report = preflight_origin(load_origin_pilot(args.manifest))
        elif args.command == "preflight-receiver":
            report = preflight_receiver(load_receiver_pilot(args.manifest))
        elif args.command == "withdraw-publication":
            report = withdraw_origin_publication(
                args.manifest, args.result_digest, args.output
            )
        else:
            report = prune_receiver_cache(args.cache_directory, args.evidence)
        print(json.dumps(report, indent=2, sort_keys=True))
    except (OSError, ssl.SSLError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
