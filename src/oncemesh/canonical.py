"""Canonical JSON and digest behavior defined by Action Protocol v0."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

MAX_SAFE_INTEGER = (2**53) - 1
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
UTC_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)


class CanonicalizationError(ValueError):
    """A value is outside the OnceMesh v0 canonical JSON profile."""


def _validate(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, (str, bool)):
        if isinstance(value, str) and any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise CanonicalizationError(f"{path}: Unicode surrogate code points are forbidden")
        return
    if isinstance(value, int):
        if not -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            raise CanonicalizationError(f"{path}: integer is outside the interoperable range")
        return
    if isinstance(value, float):
        raise CanonicalizationError(f"{path}: floating-point values are forbidden in v0")
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError(f"{path}: object keys must be strings")
            _validate(key, f"{path}.<key>")
            _validate(item, f"{path}.{key}")
        return
    raise CanonicalizationError(f"{path}: unsupported value type {type(value).__name__}")


def canonical_json(value: Any) -> bytes:
    """Return the UTF-8 canonical representation of a v0-profile JSON value."""

    _validate(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _object_digest(value: Any) -> str:
    return digest_bytes(canonical_json(value))


def _require_exact_keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"invalid {label} fields; missing={missing}, extra={extra}")


def _require_nonempty_string(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")


def _require_utc_timestamp(value: Any, label: str) -> None:
    _require_nonempty_string(value, label)
    if not UTC_TIMESTAMP_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must be an RFC 3339 UTC timestamp ending in Z")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} is not a valid timestamp") from error


def validate_action(action: dict[str, Any]) -> None:
    _require_exact_keys(
        action,
        {"spec_version", "operation", "inputs", "executor", "output_schema", "vary"},
        "action",
    )
    if action["spec_version"] != "oncemesh.action/v0":
        raise ValueError("unsupported action spec_version")
    _require_exact_keys(action["operation"], {"name", "version"}, "operation")
    _require_nonempty_string(action["operation"]["name"], "operation.name")
    _require_nonempty_string(action["operation"]["version"], "operation.version")
    _require_exact_keys(action["executor"], {"name", "version", "config"}, "executor")
    _require_nonempty_string(action["executor"]["name"], "executor.name")
    _require_nonempty_string(action["executor"]["version"], "executor.version")
    if not isinstance(action["executor"]["config"], dict):
        raise ValueError("executor.config must be an object")
    if not isinstance(action["inputs"], dict) or not isinstance(action["vary"], dict):
        raise ValueError("inputs and vary must be objects")
    _require_nonempty_string(action["output_schema"], "output_schema")
    canonical_json(action)


def validate_manifest(manifest: dict[str, Any]) -> None:
    _require_exact_keys(
        manifest,
        {"spec_version", "action_digest", "artifacts", "produced_at", "fresh_until", "producer"},
        "result manifest",
    )
    if manifest["spec_version"] != "oncemesh.result/v0":
        raise ValueError("unsupported result spec_version")
    if not isinstance(manifest["action_digest"], str) or not DIGEST_PATTERN.fullmatch(manifest["action_digest"]):
        raise ValueError("action_digest is invalid")
    _require_utc_timestamp(manifest["produced_at"], "produced_at")
    if manifest["fresh_until"] is not None:
        _require_utc_timestamp(manifest["fresh_until"], "fresh_until")
    _require_nonempty_string(manifest["producer"], "producer")
    if not isinstance(manifest["artifacts"], list):
        raise ValueError("artifacts must be an array")
    names: set[str] = set()
    for artifact in manifest["artifacts"]:
        _require_exact_keys(artifact, {"name", "digest", "size", "media_type"}, "artifact")
        _require_nonempty_string(artifact["name"], "artifact.name")
        _require_nonempty_string(artifact["media_type"], "artifact.media_type")
        if artifact["name"] in names:
            raise ValueError("artifact names must be unique")
        names.add(artifact["name"])
        if not isinstance(artifact["digest"], str) or not DIGEST_PATTERN.fullmatch(artifact["digest"]):
            raise ValueError("artifact.digest is invalid")
        if isinstance(artifact["size"], bool) or not isinstance(artifact["size"], int) or artifact["size"] < 0:
            raise ValueError("artifact.size must be a non-negative integer")
    canonical_json(manifest)


def validate_source_validation(record: dict[str, Any]) -> None:
    _require_exact_keys(
        record,
        {"spec_version", "result_digest", "validated_at", "fresh_until", "producer", "method"},
        "source validation",
    )
    if record["spec_version"] != "oncemesh.validation/v0":
        raise ValueError("unsupported source validation spec_version")
    if not isinstance(record["result_digest"], str) or not DIGEST_PATTERN.fullmatch(record["result_digest"]):
        raise ValueError("result_digest is invalid")
    _require_utc_timestamp(record["validated_at"], "validated_at")
    _require_utc_timestamp(record["fresh_until"], "fresh_until")
    validated_at = datetime.fromisoformat(record["validated_at"].replace("Z", "+00:00"))
    fresh_until = datetime.fromisoformat(record["fresh_until"].replace("Z", "+00:00"))
    if fresh_until < validated_at:
        raise ValueError("fresh_until must not precede validated_at")
    _require_nonempty_string(record["producer"], "producer")
    _require_exact_keys(
        record["method"],
        {"name", "version", "status", "etag", "last_modified"},
        "validation method",
    )
    method = record["method"]
    if method["name"] != "http.conditional" or method["version"] != "1" or method["status"] != 304:
        raise ValueError("unsupported validation method")
    for field in ("etag", "last_modified"):
        if method[field] is not None and (not isinstance(method[field], str) or not method[field]):
            raise ValueError(f"method.{field} must be null or a non-empty string")
    if method["etag"] is None and method["last_modified"] is None:
        raise ValueError("HTTP conditional validation requires at least one validator")
    canonical_json(record)


def action_digest(action: dict[str, Any]) -> str:
    validate_action(action)
    return _object_digest(action)


def manifest_digest(manifest: dict[str, Any]) -> str:
    validate_manifest(manifest)
    return _object_digest(manifest)


def validation_digest(record: dict[str, Any]) -> str:
    validate_source_validation(record)
    return _object_digest(record)
