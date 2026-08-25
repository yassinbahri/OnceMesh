"""Keyed authorization partition derivation and validation."""

from __future__ import annotations

import hashlib
import hmac
import re

from .canonical import canonical_json

AUTHORIZATION_PARTITION_PROFILE = "oncemesh.authorization-partition/v1"
AUTHORIZATION_PARTITION_DOMAIN = b"OnceMesh authorization partition v1\x00"
AUTHORIZATION_PARTITION_PATTERN = re.compile(r"^hmac-sha256:[0-9a-f]{64}$")


def validate_authorization_partition(value: str) -> None:
    if not isinstance(value, str) or not AUTHORIZATION_PARTITION_PATTERN.fullmatch(value):
        raise ValueError("authorization partition token is invalid")


def derive_authorization_partition(
    tenant: str,
    scopes: list[str] | tuple[str, ...],
    partition_key: bytes,
    *,
    subject_partition: str | None = None,
) -> str:
    if not isinstance(tenant, str) or not tenant:
        raise ValueError("tenant must be a non-empty string")
    if not isinstance(scopes, (list, tuple)) or not scopes or any(
        not isinstance(scope, str) or not scope for scope in scopes
    ):
        raise ValueError("scopes must be a non-empty string list")
    if len(set(scopes)) != len(scopes):
        raise ValueError("scopes must be unique")
    if subject_partition is not None and (
        not isinstance(subject_partition, str) or not subject_partition
    ):
        raise ValueError("subject_partition must be null or a non-empty string")
    if not isinstance(partition_key, bytes) or len(partition_key) < 32:
        raise ValueError("partition key must contain at least 32 bytes")
    claims = {
        "profile": AUTHORIZATION_PARTITION_PROFILE,
        "tenant": tenant,
        "scopes": sorted(scopes),
        "subject_partition": subject_partition,
    }
    digest = hmac.new(
        partition_key,
        AUTHORIZATION_PARTITION_DOMAIN + canonical_json(claims),
        hashlib.sha256,
    ).hexdigest()
    return f"hmac-sha256:{digest}"


def authorization_partitions_match(left: str, right: str) -> bool:
    validate_authorization_partition(left)
    validate_authorization_partition(right)
    return hmac.compare_digest(left, right)
