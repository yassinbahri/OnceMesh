"""Publication, ordered lookup, and admissibility checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .canonical import action_digest, digest_bytes, manifest_digest, validate_manifest
from .store import Store, StoreReadError
from .receipt import sign_receipt


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must contain a UTC offset")
    return parsed.astimezone(timezone.utc)


def _format_time(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Policy:
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    trusted_producers: frozenset[str] | None = None
    trusted_validation_producers: frozenset[str] | None = None
    permit_no_expiry: bool = False


@dataclass(frozen=True)
class LookupOutcome:
    hit: bool
    tier: str | None
    manifest: dict[str, Any] | None
    artifacts: dict[str, bytes]
    rejections: tuple[str, ...]
    validation: dict[str, Any] | None = None


def publish_result(
    store: Store,
    action: dict[str, Any],
    artifacts: Mapping[str, tuple[bytes, str]],
    *,
    producer: str,
    produced_at: datetime,
    fresh_until: datetime | None,
) -> dict[str, Any]:
    """Store artifact bytes and publish their immutable result manifest."""

    descriptors: list[dict[str, Any]] = []
    for name, (data, media_type) in sorted(artifacts.items()):
        digest = store.put_blob(data)
        descriptors.append(
            {"name": name, "digest": digest, "size": len(data), "media_type": media_type}
        )
    manifest = {
        "spec_version": "oncemesh.result/v0",
        "action_digest": action_digest(action),
        "artifacts": descriptors,
        "produced_at": _format_time(produced_at),
        "fresh_until": _format_time(fresh_until) if fresh_until is not None else None,
        "producer": producer,
    }
    store.put_result(manifest)
    return manifest


def publish_signed_result(
    store: Store,
    action: dict[str, Any],
    artifacts: Mapping[str, tuple[bytes, str]],
    *,
    producer: str,
    produced_at: datetime,
    fresh_until: datetime | None,
    executor_environment: dict[str, Any],
    private_key: bytes,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Publish one immutable result and its Ed25519 production receipt."""
    manifest = publish_result(
        store,
        action,
        artifacts,
        producer=producer,
        produced_at=produced_at,
        fresh_until=fresh_until,
    )
    receipt = sign_receipt(
        {
            "spec_version": "oncemesh.receipt/v0",
            "result_digest": manifest_digest(manifest),
            "producer": producer,
            "executor_environment": executor_environment,
            "signature": None,
        },
        private_key,
    )
    store.put_receipt(receipt)
    return manifest, receipt


def _evaluate(
    requested_digest: str,
    manifest: dict[str, Any],
    store: Store,
    policy: Policy,
    *,
    ignore_freshness: bool = False,
) -> tuple[dict[str, bytes] | None, str | None, dict[str, Any] | None]:
    try:
        validate_manifest(manifest)
    except ValueError:
        return None, "invalid_manifest", None
    if manifest.get("action_digest") != requested_digest:
        return None, "action_digest_mismatch", None
    if policy.trusted_producers is not None and manifest.get("producer") not in policy.trusted_producers:
        return None, "untrusted_producer", None
    selected_validation: dict[str, Any] | None = None
    fresh_until = manifest.get("fresh_until")
    if not ignore_freshness:
        is_fresh = fresh_until is not None and _parse_time(fresh_until) >= policy.now.astimezone(timezone.utc)
        if not is_fresh:
            try:
                validations = store.validations(manifest_digest(manifest))
            except StoreReadError:
                return None, "validation_read_failed", None
            for validation in validations:
                validation_trust = (
                    policy.trusted_validation_producers
                    if policy.trusted_validation_producers is not None
                    else policy.trusted_producers
                )
                trusted = validation_trust is None or validation["producer"] in validation_trust
                if trusted and _parse_time(validation["fresh_until"]) >= policy.now.astimezone(timezone.utc):
                    is_fresh = True
                    selected_validation = validation
                    break
        if not is_fresh:
            if fresh_until is None and not policy.permit_no_expiry:
                return None, "missing_freshness_rule", None
            if fresh_until is not None:
                return None, "expired", None

    artifacts: dict[str, bytes] = {}
    names: set[str] = set()
    for descriptor in manifest.get("artifacts", []):
        name = descriptor.get("name")
        if not isinstance(name, str) or name in names:
            return None, "invalid_artifact_name", None
        names.add(name)
        blob = store.get_blob(descriptor.get("digest", ""))
        if blob is None:
            return None, "artifact_missing", None
        if len(blob) != descriptor.get("size") or digest_bytes(blob) != descriptor.get("digest"):
            return None, "artifact_integrity_failure", None
        artifacts[name] = blob
    return artifacts, None, selected_validation


def reuse(
    action: dict[str, Any],
    stores: Iterable[Store],
    policy: Policy | None = None,
) -> LookupOutcome:
    """Search stores in order and return the first admissible exact hit."""

    selected_policy = policy or Policy()
    requested_digest = action_digest(action)
    rejections: list[str] = []
    for store in stores:
        try:
            candidates = store.candidates(requested_digest)
        except StoreReadError as error:
            rejections.append(f"{store.name}:{error}")
            continue
        for manifest in candidates:
            artifacts, rejection, validation = _evaluate(requested_digest, manifest, store, selected_policy)
            if rejection is not None:
                rejections.append(f"{store.name}:{rejection}")
                continue
            return LookupOutcome(True, store.name, manifest, artifacts or {}, tuple(rejections), validation)
    return LookupOutcome(False, None, None, {}, tuple(rejections))


def candidate_for_revalidation(
    action: dict[str, Any],
    stores: Iterable[Store],
    policy: Policy | None = None,
) -> LookupOutcome:
    """Return an integrity-checked candidate while deliberately ignoring freshness.

    The returned artifacts are not admissible for substitution until a source
    validation succeeds.
    """

    selected_policy = policy or Policy()
    requested_digest = action_digest(action)
    rejections: list[str] = []
    for store in stores:
        try:
            candidates = store.candidates(requested_digest)
        except StoreReadError as error:
            rejections.append(f"{store.name}:{error}")
            continue
        for manifest in candidates:
            artifacts, rejection, _ = _evaluate(
                requested_digest, manifest, store, selected_policy, ignore_freshness=True
            )
            if rejection is not None:
                rejections.append(f"{store.name}:{rejection}")
                continue
            return LookupOutcome(True, store.name, manifest, artifacts or {}, tuple(rejections))
    return LookupOutcome(False, None, None, {}, tuple(rejections))
