"""Small shared validators for versioned public JSON documents."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any


CANONICAL_UTC_PATTERN = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)


def exact_keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{label} must contain exactly {sorted(expected)}")


def format_canonical_utc(value: datetime, label: str = "timestamp") -> str:
    if value.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_canonical_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not CANONICAL_UTC_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must be a canonical UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} is not a valid timestamp") from error
    if format_canonical_utc(parsed) != value:
        raise ValueError(f"{label} must be a canonical UTC timestamp")
    return parsed
