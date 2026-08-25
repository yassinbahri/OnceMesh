"""Reloadable, fail-closed operation policy registry."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .canonical import DIGEST_PATTERN

KILL_SWITCH_VALUES = frozenset({"1", "true", "yes", "on"})
MODES = frozenset({"disabled", "shadow", "conditional-substitute", "exact-substitute", "stale-while-revalidate"})


@dataclass(frozen=True)
class OperationPolicy:
    mode: str
    trusted_result_producers: frozenset[str]
    trusted_validation_producers: frozenset[str]
    allowed_tiers: frozenset[str]
    max_validation_ttl_seconds: int
    receipt_requirement: str
    trusted_receipt_keys: frozenset[str]
    authorization_partition: str
    max_stale_seconds: int


@dataclass(frozen=True)
class PolicyResolution:
    policy: OperationPolicy | None
    reason: str
    kill_switch_active: bool = False


def _strings(value: Any, label: str) -> frozenset[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{label} must be a string array")
    if len(set(value)) != len(value):
        raise ValueError(f"{label} must contain unique values")
    return frozenset(value)


def validate_policy_document(document: dict[str, Any]) -> dict[str, OperationPolicy]:
    if not isinstance(document, dict) or set(document) != {"spec_version", "enabled", "operations"}:
        raise ValueError("invalid policy document fields")
    if document["spec_version"] != "oncemesh.policy/v0" or not isinstance(document["enabled"], bool):
        raise ValueError("invalid policy version or enabled value")
    if not isinstance(document["operations"], dict):
        raise ValueError("operations must be an object")
    policies: dict[str, OperationPolicy] = {}
    required = {
        "mode",
        "trusted_result_producers",
        "trusted_validation_producers",
        "allowed_tiers",
        "max_validation_ttl_seconds",
        "receipt_requirement",
        "trusted_receipt_keys",
        "authorization_partition",
        "max_stale_seconds",
    }
    for operation, value in document["operations"].items():
        if not isinstance(operation, str) or "/" not in operation:
            raise ValueError("operation policy keys must contain name/version")
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError(f"invalid fields for operation {operation}")
        if value["mode"] not in MODES:
            raise ValueError(f"invalid mode for operation {operation}")
        ttl = value["max_validation_ttl_seconds"]
        if isinstance(ttl, bool) or not isinstance(ttl, int) or not 1 <= ttl <= 604800:
            raise ValueError("max_validation_ttl_seconds must be from 1 through 604800")
        receipt_requirement = value["receipt_requirement"]
        if receipt_requirement not in {"optional", "required"}:
            raise ValueError("receipt_requirement must be optional or required")
        trusted_receipt_keys = _strings(value["trusted_receipt_keys"], "trusted_receipt_keys")
        if any(not DIGEST_PATTERN.fullmatch(key) for key in trusted_receipt_keys):
            raise ValueError("trusted_receipt_keys must contain SHA-256 key identifiers")
        if receipt_requirement == "required" and not trusted_receipt_keys:
            raise ValueError("required receipts need at least one trusted key")
        if receipt_requirement == "required" and value["mode"] != "exact-substitute":
            raise ValueError("required receipts currently support exact-substitute mode only")
        authorization_partition = value["authorization_partition"]
        if authorization_partition not in {"public", "required"}:
            raise ValueError("authorization_partition must be public or required")
        if authorization_partition == "required" and value["mode"] != "exact-substitute":
            raise ValueError("required authorization partitions support exact-substitute mode only")
        max_stale_seconds = value["max_stale_seconds"]
        if isinstance(max_stale_seconds, bool) or not isinstance(max_stale_seconds, int) or not 0 <= max_stale_seconds <= 604800:
            raise ValueError("max_stale_seconds must be from 0 through 604800")
        if (value["mode"] == "stale-while-revalidate") != (max_stale_seconds > 0):
            raise ValueError("only stale-while-revalidate mode requires positive max_stale_seconds")
        policies[operation] = OperationPolicy(
            mode=value["mode"],
            trusted_result_producers=_strings(
                value["trusted_result_producers"], "trusted_result_producers"
            ),
            trusted_validation_producers=_strings(
                value["trusted_validation_producers"], "trusted_validation_producers"
            ),
            allowed_tiers=_strings(value["allowed_tiers"], "allowed_tiers"),
            max_validation_ttl_seconds=ttl,
            receipt_requirement=receipt_requirement,
            trusted_receipt_keys=trusted_receipt_keys,
            authorization_partition=authorization_partition,
            max_stale_seconds=max_stale_seconds,
        )
    return policies


class FilePolicyRegistry:
    def __init__(self, path: str | Path, *, environment: Mapping[str, str] | None = None) -> None:
        self.path = Path(path)
        self.environment = environment

    def resolve(self, operation: str) -> PolicyResolution:
        environment = self.environment if self.environment is not None else os.environ
        if environment.get("ONCEMESH_DISABLE_SUBSTITUTION", "").strip().lower() in KILL_SWITCH_VALUES:
            return PolicyResolution(None, "kill_switch", True)
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
            policies = validate_policy_document(document)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            return PolicyResolution(None, "policy_error")
        if not document["enabled"]:
            return PolicyResolution(None, "policy_disabled")
        policy = policies.get(operation)
        if policy is None or policy.mode == "disabled":
            return PolicyResolution(None, "policy_disabled")
        return PolicyResolution(policy, policy.mode)
