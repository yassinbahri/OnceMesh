"""Reloadable, fail-closed Ed25519 receipt public-key registry."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from .canonical import DIGEST_PATTERN, digest_bytes
from .receipt import SIGNATURE_PROFILE

PUBLIC_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
KEY_STATUSES = frozenset({"active", "revoked"})


@dataclass(frozen=True)
class ReceiptKey:
    key_id: str
    public_key: bytes
    status: str
    producers: frozenset[str]


@dataclass(frozen=True)
class ReceiptKeyResolution:
    key: ReceiptKey | None
    reason: str


def _decode_public_key(value: Any) -> bytes:
    if not isinstance(value, str) or not PUBLIC_KEY_PATTERN.fullmatch(value):
        raise ValueError("public_key must be canonical unpadded base64url")
    try:
        decoded = base64.b64decode(value + "=", altchars=b"-_", validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError("public_key is invalid base64url") from error
    canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
    if len(decoded) != 32 or canonical != value:
        raise ValueError("public_key must encode exactly 32 bytes")
    return decoded


def encode_public_key(public_key: bytes) -> str:
    if not isinstance(public_key, bytes) or len(public_key) != 32:
        raise ValueError("Ed25519 public key must contain exactly 32 bytes")
    return base64.urlsafe_b64encode(public_key).rstrip(b"=").decode("ascii")


def validate_key_registry(document: dict[str, Any]) -> dict[str, ReceiptKey]:
    if not isinstance(document, dict) or set(document) != {"spec_version", "keys"}:
        raise ValueError("invalid key registry fields")
    if document["spec_version"] != "oncemesh.key-registry/v0":
        raise ValueError("unsupported key registry version")
    if not isinstance(document["keys"], dict):
        raise ValueError("key registry keys must be an object")
    records: dict[str, ReceiptKey] = {}
    for key_id, value in document["keys"].items():
        if not isinstance(key_id, str) or not DIGEST_PATTERN.fullmatch(key_id):
            raise ValueError("key registry key identifier is invalid")
        if not isinstance(value, dict) or set(value) != {
            "profile", "public_key", "status", "producers"
        }:
            raise ValueError("invalid key registry entry fields")
        if value["profile"] != SIGNATURE_PROFILE or value["status"] not in KEY_STATUSES:
            raise ValueError("unsupported key profile or status")
        producers = value["producers"]
        if (
            not isinstance(producers, list)
            or not producers
            or any(not isinstance(item, str) or not item for item in producers)
            or len(set(producers)) != len(producers)
        ):
            raise ValueError("key producers must be a non-empty unique string array")
        public_key = _decode_public_key(value["public_key"])
        if digest_bytes(public_key) != key_id:
            raise ValueError("key identifier does not match public key")
        records[key_id] = ReceiptKey(
            key_id, public_key, value["status"], frozenset(producers)
        )
    return records


class FileReceiptKeyRegistry:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def resolve(self, key_id: str, producer: str) -> ReceiptKeyResolution:
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
            records = validate_key_registry(document)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            return ReceiptKeyResolution(None, "receipt_registry_error")
        record = records.get(key_id)
        if record is None:
            return ReceiptKeyResolution(None, "receipt_key_unknown")
        if record.status == "revoked":
            return ReceiptKeyResolution(None, "receipt_key_revoked")
        if producer not in record.producers:
            return ReceiptKeyResolution(None, "receipt_producer_denied")
        return ReceiptKeyResolution(record, "active")
