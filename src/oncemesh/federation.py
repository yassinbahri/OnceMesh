"""Public-only, explicitly trusted federation experiment."""

from __future__ import annotations

import base64
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from threading import RLock
import tempfile
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .canonical import (
    DIGEST_PATTERN, action_digest, canonical_json, digest_bytes, manifest_digest,
    validate_action, validate_manifest,
)
from .receipt import SIGNATURE_PATTERN, SIGNATURE_PROFILE, validate_receipt, verify_receipt_for_manifest
from .store import Store

AVAILABILITY_DOMAIN = b"OnceMesh availability manifest v1\x00"


def _validate_federation_result(manifest: dict[str, Any]) -> None:
    validate_manifest(manifest)
    if manifest["spec_version"] == "oncemesh.result/v1":
        raise ValueError("federation v0 does not support result v1 lineage")


def _exact_keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"invalid {label} fields")


def _format_time(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp must be UTC RFC 3339")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc)


def _signature_value(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_signature(value: str) -> bytes:
    if not isinstance(value, str) or not SIGNATURE_PATTERN.fullmatch(value):
        raise ValueError("availability signature is not canonical base64url")
    decoded = base64.b64decode(value + "==", altchars=b"-_", validate=True)
    if len(decoded) != 64 or _signature_value(decoded) != value:
        raise ValueError("availability signature must encode 64 bytes")
    return decoded


def validate_availability(manifest: dict[str, Any], *, require_signature: bool = True) -> None:
    _exact_keys(
        manifest, {"spec_version", "peer_id", "generated_at", "entries", "signature"},
        "availability manifest",
    )
    if manifest["spec_version"] != "oncemesh.availability/v0":
        raise ValueError("unsupported availability version")
    if not isinstance(manifest["peer_id"], str) or not manifest["peer_id"]:
        raise ValueError("peer_id must be a non-empty string")
    _parse_time(manifest["generated_at"])
    if not isinstance(manifest["entries"], list):
        raise ValueError("availability entries must be an array")
    expected_order: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for entry in manifest["entries"]:
        _exact_keys(
            entry, {"action_digest", "result_digest", "operation", "artifact_bytes"},
            "availability entry",
        )
        for field in ("action_digest", "result_digest"):
            if not isinstance(entry[field], str) or not DIGEST_PATTERN.fullmatch(entry[field]):
                raise ValueError(f"availability {field} is invalid")
        _exact_keys(entry["operation"], {"name", "version"}, "availability operation")
        if any(not isinstance(entry["operation"][field], str) or not entry["operation"][field] for field in ("name", "version")):
            raise ValueError("availability operation values must be non-empty strings")
        size = entry["artifact_bytes"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ValueError("artifact_bytes must be a non-negative integer")
        identity = (entry["action_digest"], entry["result_digest"])
        if identity in seen:
            raise ValueError("availability entries must be unique")
        seen.add(identity)
        expected_order.append(identity)
    if expected_order != sorted(expected_order):
        raise ValueError("availability entries are not canonically ordered")
    signature = manifest["signature"]
    if signature is None:
        if require_signature:
            raise ValueError("availability signature is required")
    else:
        _exact_keys(signature, {"profile", "key_id", "value"}, "availability signature")
        if signature["profile"] != SIGNATURE_PROFILE:
            raise ValueError("unsupported availability signature profile")
        if not isinstance(signature["key_id"], str) or not DIGEST_PATTERN.fullmatch(signature["key_id"]):
            raise ValueError("availability key_id is invalid")
        _decode_signature(signature["value"])
    canonical_json(manifest)


def availability_signing_input(manifest: dict[str, Any]) -> bytes:
    unsigned = deepcopy(manifest)
    unsigned["signature"] = None
    validate_availability(unsigned, require_signature=False)
    return AVAILABILITY_DOMAIN + canonical_json(unsigned)


def sign_availability(manifest: dict[str, Any], private_seed: bytes) -> dict[str, Any]:
    if manifest.get("signature") is not None:
        raise ValueError("only unsigned availability can be signed")
    if not isinstance(private_seed, bytes) or len(private_seed) != 32:
        raise ValueError("availability private seed must contain exactly 32 bytes")
    signer = Ed25519PrivateKey.from_private_bytes(private_seed)
    public_key = signer.public_key().public_bytes_raw()
    signed = deepcopy(manifest)
    signed["signature"] = {
        "profile": SIGNATURE_PROFILE,
        "key_id": digest_bytes(public_key),
        "value": _signature_value(signer.sign(availability_signing_input(manifest))),
    }
    validate_availability(signed)
    return signed


def verify_availability(manifest: dict[str, Any], peer_id: str, public_key: bytes) -> bool:
    validate_availability(manifest)
    if manifest["peer_id"] != peer_id or not isinstance(public_key, bytes) or len(public_key) != 32:
        return False
    if manifest["signature"]["key_id"] != digest_bytes(public_key):
        return False
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            _decode_signature(manifest["signature"]["value"]),
            availability_signing_input(manifest),
        )
    except InvalidSignature:
        return False
    return True


@dataclass(frozen=True)
class FederationBundle:
    manifest: dict[str, Any]
    receipt: dict[str, Any]
    artifacts: dict[str, bytes]


class FederationPeer(Protocol):
    def availability(self, now: datetime | None = None) -> dict[str, Any]: ...
    def fetch_bundle(self, result_digest: str) -> FederationBundle | None: ...


class PublicPeerCatalog:
    def __init__(
        self,
        peer_id: str,
        store: Store,
        availability_private_seed: bytes,
        receipt_public_keys: Mapping[str, bytes],
    ) -> None:
        if not peer_id:
            raise ValueError("peer_id must not be empty")
        if len(availability_private_seed) != 32:
            raise ValueError("availability private seed must contain 32 bytes")
        if getattr(store, "federation_import_only", False):
            raise ValueError("imported federation results cannot be re-exported")
        self.peer_id = peer_id
        self.store = store
        self._seed = bytes(availability_private_seed)
        self._receipt_keys = dict(receipt_public_keys)
        self._published: dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = {}

    def publish(
        self,
        action: dict[str, Any],
        manifest: dict[str, Any],
        receipt: dict[str, Any],
        *,
        classification: str,
    ) -> str:
        if classification != "public":
            raise ValueError("federation catalog accepts explicitly public results only")
        validate_action(action)
        _validate_federation_result(manifest)
        validate_receipt(receipt, require_signature=True)
        if manifest["action_digest"] != action_digest(action):
            raise ValueError("result does not match published action")
        result_digest = manifest_digest(manifest)
        signature = receipt["signature"]
        public_key = self._receipt_keys.get(signature["key_id"])
        if public_key is None or not verify_receipt_for_manifest(receipt, manifest, public_key):
            raise ValueError("result receipt is not trusted by origin catalog")
        for descriptor in manifest["artifacts"]:
            blob = self.store.get_blob(descriptor["digest"])
            if blob is None or len(blob) != descriptor["size"] or digest_bytes(blob) != descriptor["digest"]:
                raise ValueError("published artifact is missing or corrupt")
        self._published[result_digest] = (deepcopy(action), deepcopy(manifest), deepcopy(receipt))
        return result_digest

    def withdraw(self, result_digest: str) -> bool:
        return self._published.pop(result_digest, None) is not None

    def availability(self, now: datetime | None = None) -> dict[str, Any]:
        entries = []
        for result_digest, (action, manifest, _) in self._published.items():
            entries.append({
                "action_digest": action_digest(action),
                "result_digest": result_digest,
                "operation": deepcopy(action["operation"]),
                "artifact_bytes": sum(item["size"] for item in manifest["artifacts"]),
            })
        entries.sort(key=lambda item: (item["action_digest"], item["result_digest"]))
        return sign_availability({
            "spec_version": "oncemesh.availability/v0",
            "peer_id": self.peer_id,
            "generated_at": _format_time(now or datetime.now(timezone.utc)),
            "entries": entries,
            "signature": None,
        }, self._seed)

    def fetch_bundle(self, result_digest: str) -> FederationBundle | None:
        published = self._published.get(result_digest)
        if published is None:
            return None
        _, manifest, receipt = published
        artifacts = {
            descriptor["name"]: self.store.get_blob(descriptor["digest"])
            for descriptor in manifest["artifacts"]
        }
        if any(value is None for value in artifacts.values()):
            return None
        return FederationBundle(deepcopy(manifest), deepcopy(receipt), artifacts)  # type: ignore[arg-type]


@dataclass(frozen=True)
class FederationPeerConfig:
    peer_id: str
    availability_public_key: bytes
    receipt_public_keys: Mapping[str, bytes]
    trusted_producers: frozenset[str]
    allowed_operations: frozenset[str]
    max_entries: int = 1000
    max_artifact_bytes: int = 10_000_000
    max_transfer_bytes: int = 50_000_000
    max_availability_age_seconds: int = 300
    max_future_clock_skew_seconds: int = 30
    retention_seconds: int = 86400

    def __post_init__(self) -> None:
        if (
            not isinstance(self.peer_id, str) or not self.peer_id
            or not isinstance(self.availability_public_key, bytes)
            or len(self.availability_public_key) != 32
        ):
            raise ValueError("peer identity and 32-byte availability key are required")
        for value, label, minimum, maximum in (
            (self.max_entries, "max_entries", 1, 100_000),
            (self.max_artifact_bytes, "max_artifact_bytes", 1, 1_000_000_000),
            (self.max_transfer_bytes, "max_transfer_bytes", 1, 1_000_000_000),
            (self.max_availability_age_seconds, "max_availability_age_seconds", 1, 86_400),
            (self.max_future_clock_skew_seconds, "max_future_clock_skew_seconds", 0, 3600),
            (self.retention_seconds, "retention_seconds", 1, 31_536_000),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                raise ValueError(f"{label} is outside the supported range")
        if not self.trusted_producers or not self.allowed_operations:
            raise ValueError("trusted producers and allowed operations must not be empty")
        if any(not isinstance(item, str) or not item for item in self.trusted_producers):
            raise ValueError("trusted producer values must be non-empty strings")
        if any(not isinstance(item, str) or "/" not in item or item.startswith("/") or item.endswith("/") for item in self.allowed_operations):
            raise ValueError("allowed operations must use non-empty name/version values")
        receipt_keys = dict(self.receipt_public_keys)
        for key_id, public_key in receipt_keys.items():
            if (
                not isinstance(key_id, str) or not DIGEST_PATTERN.fullmatch(key_id)
                or not isinstance(public_key, bytes) or len(public_key) != 32
                or digest_bytes(public_key) != key_id
            ):
                raise ValueError("receipt public key mapping is invalid")
        object.__setattr__(self, "availability_public_key", bytes(self.availability_public_key))
        object.__setattr__(self, "receipt_public_keys", MappingProxyType(receipt_keys))
        object.__setattr__(self, "trusted_producers", frozenset(self.trusted_producers))
        object.__setattr__(self, "allowed_operations", frozenset(self.allowed_operations))


@dataclass(frozen=True)
class FederationImportOutcome:
    hit: bool
    reason: str
    result_digest: str | None = None
    bytes_imported: int = 0


class FederationCacheStore:
    """Dedicated leased cache for imported, non-exportable federation results."""

    federation_import_only = True

    def __init__(self, name: str = "federation", *, clock: Callable[[], datetime] | None = None) -> None:
        self.name = name
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._blobs: dict[str, bytes] = {}
        self._results: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._receipts: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._validations: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._leases: dict[str, datetime] = {}

    def import_bundle(self, bundle: FederationBundle, retain_until: datetime) -> None:
        result_digest = manifest_digest(bundle.manifest)
        for descriptor in bundle.manifest["artifacts"]:
            self._blobs[descriptor["digest"]] = bytes(bundle.artifacts[descriptor["name"]])
        self._results[bundle.manifest["action_digest"]].append(deepcopy(bundle.manifest))
        self._receipts[result_digest].append(deepcopy(bundle.receipt))
        self._leases[result_digest] = retain_until.astimezone(timezone.utc)

    def prune(self, now: datetime | None = None) -> int:
        selected = (now or self._clock()).astimezone(timezone.utc)
        expired = {digest for digest, until in self._leases.items() if until <= selected}
        if not expired:
            return 0
        for action, manifests in list(self._results.items()):
            retained = [item for item in manifests if manifest_digest(item) not in expired]
            if retained:
                self._results[action] = retained
            else:
                self._results.pop(action, None)
        for digest in expired:
            self._leases.pop(digest, None)
            self._receipts.pop(digest, None)
            self._validations.pop(digest, None)
        live_blobs = {
            descriptor["digest"]
            for manifests in self._results.values()
            for manifest in manifests
            for descriptor in manifest["artifacts"]
        }
        for digest in list(self._blobs):
            if digest not in live_blobs:
                self._blobs.pop(digest, None)
        return len(expired)

    def put_blob(self, data: bytes) -> str:
        raise ValueError("federation cache accepts only verified import bundles")

    def get_blob(self, digest: str) -> bytes | None:
        self.prune()
        value = self._blobs.get(digest)
        return bytes(value) if value is not None else None

    def put_result(self, manifest: dict[str, Any]) -> None:
        raise ValueError("federation cache accepts only verified import bundles")

    def candidates(self, requested_action_digest: str) -> list[dict[str, Any]]:
        self.prune()
        return deepcopy(list(reversed(self._results.get(requested_action_digest, []))))

    def put_validation(self, record: dict[str, Any]) -> None:
        raise ValueError("federation cache does not accept local validation publication")

    def validations(self, result_digest: str) -> list[dict[str, Any]]:
        self.prune()
        return deepcopy(self._validations.get(result_digest, []))

    def put_receipt(self, receipt: dict[str, Any]) -> None:
        raise ValueError("federation cache accepts receipts only in verified bundles")

    def receipts(self, result_digest: str) -> list[dict[str, Any]]:
        self.prune()
        return deepcopy(self._receipts.get(result_digest, []))


class FilesystemFederationCacheStore:
    """Durable single-process leased cache for pilot receiver evidence."""

    federation_import_only = True

    def __init__(
        self,
        root: str | Path,
        name: str = "federation-filesystem",
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.name = name
        self.root = Path(root).resolve()
        self.entry_root = self.root / "entries"
        self.blob_root = self.root / "blobs" / "sha256"
        self.entry_root.mkdir(parents=True, exist_ok=True)
        self.blob_root.mkdir(parents=True, exist_ok=True)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()

    @staticmethod
    def _hex_digest(value: str) -> str:
        if not isinstance(value, str) or not DIGEST_PATTERN.fullmatch(value):
            raise ValueError("invalid federation cache digest")
        return value.removeprefix("sha256:")

    def _entry_path(self, result_digest: str) -> Path:
        return self.entry_root / f"{self._hex_digest(result_digest)}.json"

    def _blob_path(self, blob_digest: str) -> Path:
        value = self._hex_digest(blob_digest)
        return self.blob_root / value[:2] / value[2:]

    @staticmethod
    def _write_atomic(path: Path, data: bytes, *, replace: bool) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(prefix=".oncemesh-federation-", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            if replace:
                os.replace(temporary, path)
            else:
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    pass
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _read_entries(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self.entry_root.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise ValueError("federation cache entry cannot be read") from error
            _exact_keys(
                record,
                {"spec_version", "result_digest", "imported_at", "retain_until", "manifest", "receipt"},
                "federation cache entry",
            )
            if record["spec_version"] != "oncemesh.federation-cache-entry/v0":
                raise ValueError("unsupported federation cache entry")
            _validate_federation_result(record["manifest"])
            validate_receipt(record["receipt"], require_signature=True)
            if manifest_digest(record["manifest"]) != record["result_digest"]:
                raise ValueError("federation cache result digest mismatch")
            if record["receipt"]["result_digest"] != record["result_digest"]:
                raise ValueError("federation cache receipt binding mismatch")
            if path != self._entry_path(record["result_digest"]):
                raise ValueError("federation cache entry path mismatch")
            _parse_time(record["imported_at"])
            _parse_time(record["retain_until"])
            records.append(record)
        return records

    def import_bundle(self, bundle: FederationBundle, retain_until: datetime) -> None:
        _validate_federation_result(bundle.manifest)
        validate_receipt(bundle.receipt, require_signature=True)
        result_digest = manifest_digest(bundle.manifest)
        if bundle.receipt["result_digest"] != result_digest:
            raise ValueError("federation bundle receipt binding mismatch")
        expected_names = {item["name"] for item in bundle.manifest["artifacts"]}
        if set(bundle.artifacts) != expected_names:
            raise ValueError("federation bundle artifact names mismatch")
        selected_until = retain_until.astimezone(timezone.utc)
        imported_at = self._clock().astimezone(timezone.utc)
        if selected_until <= imported_at:
            raise ValueError("federation cache lease must end after import")
        with self._lock:
            for descriptor in bundle.manifest["artifacts"]:
                blob = bundle.artifacts[descriptor["name"]]
                if len(blob) != descriptor["size"] or digest_bytes(blob) != descriptor["digest"]:
                    raise ValueError("federation bundle artifact integrity failure")
                path = self._blob_path(descriptor["digest"])
                if path.exists():
                    existing = path.read_bytes()
                    if digest_bytes(existing) != descriptor["digest"]:
                        raise ValueError("federation cache existing blob is corrupt")
                else:
                    self._write_atomic(path, blob, replace=False)
            record = {
                "spec_version": "oncemesh.federation-cache-entry/v0",
                "result_digest": result_digest,
                "imported_at": _format_time(imported_at),
                "retain_until": _format_time(selected_until),
                "manifest": deepcopy(bundle.manifest),
                "receipt": deepcopy(bundle.receipt),
            }
            self._write_atomic(
                self._entry_path(result_digest), canonical_json(record) + b"\n", replace=True
            )

    def prune(self, now: datetime | None = None) -> int:
        selected = (now or self._clock()).astimezone(timezone.utc)
        with self._lock:
            records = self._read_entries()
            expired = [item for item in records if _parse_time(item["retain_until"]) <= selected]
            for record in expired:
                self._entry_path(record["result_digest"]).unlink(missing_ok=True)
            retained = [item for item in records if item not in expired]
            live_blobs = {
                descriptor["digest"]
                for record in retained
                for descriptor in record["manifest"]["artifacts"]
            }
            for path in self.blob_root.glob("*/*"):
                digest = f"sha256:{path.parent.name}{path.name}"
                if digest not in live_blobs:
                    path.unlink(missing_ok=True)
            for directory in self.blob_root.glob("*"):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            return len(expired)

    def summary(self, *, prune: bool = True) -> dict[str, int]:
        if prune:
            self.prune()
        with self._lock:
            return {
                "entries": len(self._read_entries()),
                "blobs": sum(1 for path in self.blob_root.glob("*/*") if path.is_file()),
            }

    def lease_until(self, result_digest: str) -> datetime | None:
        self.prune()
        with self._lock:
            for record in self._read_entries():
                if record["result_digest"] == result_digest:
                    return _parse_time(record["retain_until"])
        return None

    def put_blob(self, data: bytes) -> str:
        raise ValueError("federation cache accepts only verified import bundles")

    def get_blob(self, digest: str) -> bytes | None:
        self.prune()
        path = self._blob_path(digest)
        if not path.is_file():
            return None
        value = path.read_bytes()
        if digest_bytes(value) != digest:
            raise ValueError("federation cache blob integrity failure")
        return value

    def put_result(self, manifest: dict[str, Any]) -> None:
        raise ValueError("federation cache accepts only verified import bundles")

    def candidates(self, requested_action_digest: str) -> list[dict[str, Any]]:
        self.prune()
        with self._lock:
            records = [
                item for item in self._read_entries()
                if item["manifest"]["action_digest"] == requested_action_digest
            ]
        records.sort(key=lambda item: _parse_time(item["imported_at"]), reverse=True)
        return deepcopy([item["manifest"] for item in records])

    def put_validation(self, record: dict[str, Any]) -> None:
        raise ValueError("federation cache does not accept local validation publication")

    def validations(self, result_digest: str) -> list[dict[str, Any]]:
        self.prune()
        return []

    def put_receipt(self, receipt: dict[str, Any]) -> None:
        raise ValueError("federation cache accepts receipts only in verified bundles")

    def receipts(self, result_digest: str) -> list[dict[str, Any]]:
        self.prune()
        with self._lock:
            return deepcopy([
                item["receipt"] for item in self._read_entries()
                if item["result_digest"] == result_digest
            ])


def import_from_peer(
    action: dict[str, Any],
    peer: FederationPeer,
    config: FederationPeerConfig,
    destination: FederationCacheStore,
    *,
    now: datetime | None = None,
) -> FederationImportOutcome:
    validate_action(action)
    observed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        availability = peer.availability(observed_at)
        validate_availability(availability)
    except (ValueError, TypeError):
        return FederationImportOutcome(False, "availability_invalid")
    if len(availability["entries"]) > config.max_entries:
        return FederationImportOutcome(False, "availability_limit_exceeded")
    if not verify_availability(availability, config.peer_id, config.availability_public_key):
        return FederationImportOutcome(False, "availability_untrusted")
    generated_at = _parse_time(availability["generated_at"])
    if generated_at < observed_at - timedelta(seconds=config.max_availability_age_seconds):
        return FederationImportOutcome(False, "availability_expired")
    if generated_at > observed_at + timedelta(seconds=config.max_future_clock_skew_seconds):
        return FederationImportOutcome(False, "availability_from_future")
    requested_digest = action_digest(action)
    entry = next((item for item in availability["entries"] if item["action_digest"] == requested_digest), None)
    if entry is None:
        return FederationImportOutcome(False, "not_available")
    operation_key = f"{entry['operation']['name']}/{entry['operation']['version']}"
    if entry["operation"] != action["operation"] or operation_key not in config.allowed_operations:
        return FederationImportOutcome(False, "operation_denied")
    if entry["artifact_bytes"] > config.max_transfer_bytes:
        return FederationImportOutcome(False, "transfer_limit_exceeded")
    bundle = peer.fetch_bundle(entry["result_digest"])
    if bundle is None:
        return FederationImportOutcome(False, "bundle_unavailable")
    try:
        _validate_federation_result(bundle.manifest)
        validate_receipt(bundle.receipt, require_signature=True)
        if manifest_digest(bundle.manifest) != entry["result_digest"]:
            raise ValueError("result digest mismatch")
        if bundle.manifest["action_digest"] != requested_digest:
            raise ValueError("action digest mismatch")
        if bundle.manifest["producer"] not in config.trusted_producers:
            return FederationImportOutcome(False, "producer_untrusted")
        signature = bundle.receipt["signature"]
        receipt_key = config.receipt_public_keys.get(signature["key_id"])
        if receipt_key is None:
            return FederationImportOutcome(False, "receipt_key_untrusted")
        if not verify_receipt_for_manifest(bundle.receipt, bundle.manifest, receipt_key):
            return FederationImportOutcome(False, "receipt_invalid")
        if set(bundle.artifacts) != {item["name"] for item in bundle.manifest["artifacts"]}:
            raise ValueError("artifact names mismatch")
        total = 0
        for descriptor in bundle.manifest["artifacts"]:
            blob = bundle.artifacts[descriptor["name"]]
            if len(blob) > config.max_artifact_bytes:
                return FederationImportOutcome(False, "artifact_limit_exceeded")
            if len(blob) != descriptor["size"] or digest_bytes(blob) != descriptor["digest"]:
                raise ValueError("artifact integrity failure")
            total += len(blob)
            if total > config.max_transfer_bytes:
                return FederationImportOutcome(False, "transfer_limit_exceeded")
        if total != entry["artifact_bytes"]:
            raise ValueError("advertised byte count mismatch")
    except (ValueError, TypeError, KeyError):
        return FederationImportOutcome(False, "bundle_invalid")
    destination.import_bundle(bundle, observed_at + timedelta(seconds=config.retention_seconds))
    return FederationImportOutcome(True, "imported", entry["result_digest"], total)
