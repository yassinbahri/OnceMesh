"""Strict Ed25519 production-receipt signing and verification."""

from __future__ import annotations

import base64
from copy import deepcopy
import re
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .canonical import DIGEST_PATTERN, canonical_json, digest_bytes, manifest_digest, validate_manifest

SIGNATURE_PROFILE = "oncemesh.ed25519/v1"
DOMAIN_SEPARATOR = b"OnceMesh receipt signature v1\x00"
SIGNATURE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{86}$")


def _exact_keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"invalid {label} fields")


def validate_receipt(receipt: dict[str, Any], *, require_signature: bool = False) -> None:
    _exact_keys(
        receipt,
        {"spec_version", "result_digest", "producer", "executor_environment", "signature"},
        "receipt",
    )
    if receipt["spec_version"] != "oncemesh.receipt/v0":
        raise ValueError("unsupported receipt spec_version")
    if not isinstance(receipt["result_digest"], str) or not DIGEST_PATTERN.fullmatch(
        receipt["result_digest"]
    ):
        raise ValueError("receipt result_digest is invalid")
    if not isinstance(receipt["producer"], str) or not receipt["producer"]:
        raise ValueError("receipt producer must be a non-empty string")
    if not isinstance(receipt["executor_environment"], dict):
        raise ValueError("executor_environment must be an object")
    signature = receipt["signature"]
    if signature is None:
        if require_signature:
            raise ValueError("receipt signature is required")
    else:
        _exact_keys(signature, {"profile", "key_id", "value"}, "receipt signature")
        if signature["profile"] != SIGNATURE_PROFILE:
            raise ValueError("unsupported receipt signature profile")
        if not isinstance(signature["key_id"], str) or not DIGEST_PATTERN.fullmatch(
            signature["key_id"]
        ):
            raise ValueError("receipt signature key_id is invalid")
        if not isinstance(signature["value"], str) or not SIGNATURE_PATTERN.fullmatch(
            signature["value"]
        ):
            raise ValueError("receipt signature value is not canonical base64url")
        _decode_signature(signature["value"])
    canonical_json(receipt)


def receipt_signing_input(receipt: dict[str, Any]) -> bytes:
    unsigned = dict(receipt)
    unsigned["signature"] = None
    validate_receipt(unsigned)
    return DOMAIN_SEPARATOR + canonical_json(unsigned)


def _encode_signature(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_signature(value: str) -> bytes:
    try:
        decoded = base64.b64decode(value + "==", altchars=b"-_", validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError("receipt signature value is invalid base64url") from error
    if len(decoded) != 64 or _encode_signature(decoded) != value:
        raise ValueError("receipt signature must be canonical encoding of 64 bytes")
    return decoded


def raw_public_key(private_key: bytes) -> bytes:
    if not isinstance(private_key, bytes) or len(private_key) != 32:
        raise ValueError("Ed25519 private key seed must contain exactly 32 bytes")
    return Ed25519PrivateKey.from_private_bytes(private_key).public_key().public_bytes_raw()


def sign_receipt(receipt: dict[str, Any], private_key: bytes) -> dict[str, Any]:
    if receipt.get("signature") is not None:
        raise ValueError("only an unsigned receipt can be signed")
    validate_receipt(receipt)
    if not isinstance(private_key, bytes) or len(private_key) != 32:
        raise ValueError("Ed25519 private key seed must contain exactly 32 bytes")
    signer = Ed25519PrivateKey.from_private_bytes(private_key)
    public_key = signer.public_key().public_bytes_raw()
    signature = signer.sign(receipt_signing_input(receipt))
    signed = deepcopy(receipt)
    signed["signature"] = {
        "profile": SIGNATURE_PROFILE,
        "key_id": digest_bytes(public_key),
        "value": _encode_signature(signature),
    }
    validate_receipt(signed, require_signature=True)
    return signed


def verify_receipt(receipt: dict[str, Any], public_key: bytes) -> bool:
    validate_receipt(receipt, require_signature=True)
    if not isinstance(public_key, bytes) or len(public_key) != 32:
        raise ValueError("Ed25519 public key must contain exactly 32 bytes")
    signature = receipt["signature"]
    if signature["key_id"] != digest_bytes(public_key):
        return False
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            _decode_signature(signature["value"]), receipt_signing_input(receipt)
        )
    except InvalidSignature:
        return False
    return True


def verify_receipt_for_manifest(
    receipt: dict[str, Any], manifest: dict[str, Any], public_key: bytes
) -> bool:
    validate_manifest(manifest)
    validate_receipt(receipt, require_signature=True)
    if receipt["result_digest"] != manifest_digest(manifest):
        return False
    if receipt["producer"] != manifest["producer"]:
        return False
    return verify_receipt(receipt, public_key)


def receipt_digest(receipt: dict[str, Any]) -> str:
    validate_receipt(receipt)
    return digest_bytes(canonical_json(receipt))
