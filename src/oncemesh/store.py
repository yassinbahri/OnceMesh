"""Storage interfaces and reference local stores."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from threading import RLock
from typing import Any, Protocol

from .canonical import (
    DIGEST_PATTERN,
    canonical_json,
    digest_bytes,
    manifest_digest,
    validate_manifest,
    validate_source_validation,
    validation_digest,
)
from .receipt import receipt_digest, validate_receipt


class StoreReadError(RuntimeError):
    """Stored cache data could not be read safely."""


class Store(Protocol):
    name: str

    def put_blob(self, data: bytes) -> str: ...

    def get_blob(self, digest: str) -> bytes | None: ...

    def put_result(self, manifest: dict[str, Any]) -> None: ...

    def candidates(self, requested_action_digest: str) -> list[dict[str, Any]]: ...

    def put_validation(self, record: dict[str, Any]) -> None: ...

    def validations(self, result_digest: str) -> list[dict[str, Any]]: ...

    def put_receipt(self, receipt: dict[str, Any]) -> None: ...

    def receipts(self, result_digest: str) -> list[dict[str, Any]]: ...


class MemoryStore:
    """An action cache and CAS suitable for conformance tests and local trials."""

    def __init__(self, name: str = "local") -> None:
        self.name = name
        self._blobs: dict[str, bytes] = {}
        self._results: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._validations: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._receipts: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._lock = RLock()

    def put_blob(self, data: bytes) -> str:
        digest = digest_bytes(data)
        with self._lock:
            self._blobs[digest] = bytes(data)
        return digest

    def get_blob(self, digest: str) -> bytes | None:
        with self._lock:
            value = self._blobs.get(digest)
        return bytes(value) if value is not None else None

    def put_result(self, manifest: dict[str, Any]) -> None:
        validate_manifest(manifest)
        with self._lock:
            self._results[manifest["action_digest"]].append(deepcopy(manifest))

    def candidates(self, requested_action_digest: str) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(list(reversed(self._results.get(requested_action_digest, []))))

    def put_validation(self, record: dict[str, Any]) -> None:
        validate_source_validation(record)
        with self._lock:
            self._validations[record["result_digest"]].append(deepcopy(record))

    def validations(self, result_digest: str) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(list(reversed(self._validations.get(result_digest, []))))

    def put_receipt(self, receipt: dict[str, Any]) -> None:
        validate_receipt(receipt)
        with self._lock:
            self._receipts[receipt["result_digest"]].append(deepcopy(receipt))

    def receipts(self, result_digest: str) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(list(reversed(self._receipts.get(result_digest, []))))


class FilesystemStore:
    """Persistent v0 store with atomic immutable writes and validated paths."""

    def __init__(self, root: str | Path, name: str = "local-filesystem") -> None:
        self.name = name
        self.root = Path(root).resolve()
        self.blob_root = self.root / "blobs" / "sha256"
        self.action_root = self.root / "actions" / "sha256"
        self.validation_root = self.root / "validations" / "sha256"
        self.receipt_root = self.root / "receipts" / "sha256"
        self.blob_root.mkdir(parents=True, exist_ok=True)
        self.action_root.mkdir(parents=True, exist_ok=True)
        self.validation_root.mkdir(parents=True, exist_ok=True)
        self.receipt_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _hex_digest(digest: str) -> str:
        if not isinstance(digest, str) or not DIGEST_PATTERN.fullmatch(digest):
            raise ValueError("invalid SHA-256 digest")
        return digest.removeprefix("sha256:")

    def _blob_path(self, digest: str) -> Path:
        value = self._hex_digest(digest)
        return self.blob_root / value[:2] / value[2:]

    def _action_path(self, digest: str) -> Path:
        return self.action_root / self._hex_digest(digest)

    def _validation_path(self, result_digest: str) -> Path:
        return self.validation_root / self._hex_digest(result_digest)

    def _receipt_path(self, result_digest: str) -> Path:
        return self.receipt_root / self._hex_digest(result_digest)

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            return
        handle, temporary_name = tempfile.mkstemp(prefix=".oncemesh-", dir=path.parent)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(handle, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            try:
                # A same-filesystem hard link publishes the completed temporary
                # file atomically and cannot replace an existing immutable object.
                os.link(temporary_path, path)
            except FileExistsError:
                pass
        finally:
            temporary_path.unlink(missing_ok=True)

    def put_blob(self, data: bytes) -> str:
        digest = digest_bytes(data)
        self._atomic_write(self._blob_path(digest), data)
        return digest

    def get_blob(self, digest: str) -> bytes | None:
        path = self._blob_path(digest)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as error:
            raise StoreReadError("blob_read_failed") from error

    def put_result(self, manifest: dict[str, Any]) -> None:
        validate_manifest(manifest)
        digest = manifest_digest(manifest).removeprefix("sha256:")
        path = self._action_path(manifest["action_digest"]) / f"{digest}.json"
        self._atomic_write(path, canonical_json(manifest))

    def candidates(self, requested_action_digest: str) -> list[dict[str, Any]]:
        directory = self._action_path(requested_action_digest)
        if not directory.exists():
            return []
        manifests: list[dict[str, Any]] = []
        try:
            paths = list(directory.glob("*.json"))
            for path in paths:
                value = json.loads(path.read_text(encoding="utf-8"))
                validate_manifest(value)
                manifests.append(value)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise StoreReadError("manifest_read_failed") from error
        return sorted(manifests, key=lambda item: item["produced_at"], reverse=True)

    def put_validation(self, record: dict[str, Any]) -> None:
        validate_source_validation(record)
        digest = validation_digest(record).removeprefix("sha256:")
        path = self._validation_path(record["result_digest"]) / f"{digest}.json"
        self._atomic_write(path, canonical_json(record))

    def validations(self, result_digest: str) -> list[dict[str, Any]]:
        directory = self._validation_path(result_digest)
        if not directory.exists():
            return []
        records: list[dict[str, Any]] = []
        try:
            for path in directory.glob("*.json"):
                value = json.loads(path.read_text(encoding="utf-8"))
                validate_source_validation(value)
                if value["result_digest"] != result_digest:
                    raise ValueError("validation record is indexed under the wrong result")
                records.append(value)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise StoreReadError("validation_read_failed") from error
        return sorted(records, key=lambda item: item["validated_at"], reverse=True)

    def put_receipt(self, receipt: dict[str, Any]) -> None:
        validate_receipt(receipt)
        digest = receipt_digest(receipt).removeprefix("sha256:")
        path = self._receipt_path(receipt["result_digest"]) / f"{digest}.json"
        self._atomic_write(path, canonical_json(receipt))

    def receipts(self, result_digest: str) -> list[dict[str, Any]]:
        directory = self._receipt_path(result_digest)
        if not directory.exists():
            return []
        records: list[dict[str, Any]] = []
        try:
            for path in directory.glob("*.json"):
                value = json.loads(path.read_text(encoding="utf-8"))
                validate_receipt(value)
                if value["result_digest"] != result_digest:
                    raise ValueError("receipt is indexed under the wrong result")
                records.append(value)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise StoreReadError("receipt_read_failed") from error
        return sorted(records, key=receipt_digest)
