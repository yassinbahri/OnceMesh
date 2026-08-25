"""Reusable safe codecs for integration adapters."""

from __future__ import annotations

import json
import math
from typing import Any

from ..execution_cache import EncodedExecutionValue


def validate_json_value(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, str):
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise ValueError(f"{path}: Unicode surrogate code points are forbidden")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path}: non-finite floats are not JSON values")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            validate_json_value(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path}: JSON object keys must be strings")
            validate_json_value(item, f"{path}.{key}")
        return
    raise ValueError(f"{path}: unsupported JSON value type {type(value).__name__}")


class JsonValueCodec:
    """Deterministic safe JSON codec with an integration-specific identity."""

    type_tag = "json"

    def __init__(self, serializer_id: str) -> None:
        if not isinstance(serializer_id, str) or not serializer_id:
            raise ValueError("serializer_id must be a non-empty string")
        self.serializer_id = serializer_id

    def encode(self, value: Any) -> EncodedExecutionValue:
        validate_json_value(value)
        payload = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return EncodedExecutionValue(self.type_tag, payload)

    def decode(self, value: EncodedExecutionValue) -> Any:
        if value.type_tag != self.type_tag:
            raise ValueError("JSON cache value has the wrong type tag")

        def reject_constant(constant: str) -> None:
            raise ValueError(f"invalid JSON constant {constant}")

        decoded = json.loads(value.payload.decode("utf-8"), parse_constant=reject_constant)
        validate_json_value(decoded)
        return decoded
