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
    trusted_invalidation_producers: frozenset[str] | None = None
    permit_no_expiry: bool = False
    require_lineage: bool = False
    max_dependency_depth: int = 8
    max_dependency_count: int = 64

    def __post_init__(self) -> None:
        for name in ("max_dependency_depth", "max_dependency_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


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
    dependencies: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Store artifact bytes and publish their immutable result manifest."""

    descriptors: list[dict[str, Any]] = []
    for name, (data, media_type) in sorted(artifacts.items()):
        digest = store.put_blob(data)
        descriptors.append(
            {"name": name, "digest": digest, "size": len(data), "media_type": media_type}
        )
    manifest: dict[str, Any] = {
        "spec_version": (
            "oncemesh.result/v1" if dependencies is not None else "oncemesh.result/v0"
        ),
        "action_digest": action_digest(action),
        "artifacts": descriptors,
        "produced_at": _format_time(produced_at),
        "fresh_until": _format_time(fresh_until) if fresh_until is not None else None,
        "producer": producer,
    }
    if dependencies is not None:
        manifest["dependencies"] = [
            {"name": name, "result_digest": result_digest}
            for name, result_digest in sorted(dependencies.items())
        ]
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
    dependencies: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Publish one immutable result and its Ed25519 production receipt."""
    manifest = publish_result(
        store,
        action,
        artifacts,
        producer=producer,
        produced_at=produced_at,
        fresh_until=fresh_until,
        dependencies=dependencies,
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


def publish_invalidation(
    store: Store,
    result_digest: str,
    *,
    producer: str,
    invalidated_at: datetime,
    reason: str,
) -> dict[str, Any]:
    """Publish a monotonic early-invalidation signal for an exact result."""

    record = {
        "spec_version": "oncemesh.invalidation/v0",
        "result_digest": result_digest,
        "invalidated_at": _format_time(invalidated_at),
        "producer": producer,
        "reason": reason,
    }
    store.put_invalidation(record)
    return record


@dataclass
class _DependencyTraversal:
    active: set[str] = field(default_factory=set)
    edges: int = 0


def _effective_invalidated(
    manifest: dict[str, Any],
    store: Store,
    policy: Policy,
    *,
    required: bool,
) -> str | None:
    reader = getattr(store, "invalidations", None)
    if reader is None:
        return "invalidation_lookup_unsupported" if required else None
    try:
        records = reader(manifest_digest(manifest))
    except StoreReadError:
        return "invalidation_read_failed"
    invalidation_trust = (
        policy.trusted_invalidation_producers
        if policy.trusted_invalidation_producers is not None
        else policy.trusted_producers
    )
    evaluation_time = policy.now.astimezone(timezone.utc)
    for record in records:
        trusted = invalidation_trust is None or record["producer"] in invalidation_trust
        if trusted and _parse_time(record["invalidated_at"]) <= evaluation_time:
            return "invalidated"
    return None


def _locate_result(
    result_digest: str,
    stores: tuple[Store, ...],
) -> tuple[dict[str, Any] | None, Store | None, str | None]:
    read_failed = False
    supported = False
    for store in stores:
        reader = getattr(store, "result", None)
        if reader is None:
            continue
        supported = True
        try:
            manifest = reader(result_digest)
        except StoreReadError:
            read_failed = True
            continue
        if manifest is None:
            continue
        try:
            validate_manifest(manifest)
            if manifest_digest(manifest) != result_digest:
                return None, None, "dependency_digest_mismatch"
        except ValueError:
            return None, None, "dependency_invalid_manifest"
        return manifest, store, None
    if read_failed:
        return None, None, "dependency_read_failed"
    if not supported:
        return None, None, "dependency_lookup_unsupported"
    return None, None, "dependency_missing"


def _evaluate(
    requested_digest: str,
    manifest: dict[str, Any],
    store: Store,
    policy: Policy,
    *,
    stores: tuple[Store, ...],
    traversal: _DependencyTraversal,
    depth: int = 0,
    ignore_freshness: bool = False,
) -> tuple[dict[str, bytes] | None, str | None, dict[str, Any] | None]:
    try:
        validate_manifest(manifest)
    except ValueError:
        return None, "invalid_manifest", None
    if manifest.get("action_digest") != requested_digest:
        return None, "action_digest_mismatch", None
    if policy.require_lineage and manifest["spec_version"] != "oncemesh.result/v1":
        return None, "lineage_required", None
    exact_result_digest = manifest_digest(manifest)
    if depth > policy.max_dependency_depth:
        return None, "dependency_depth_exceeded", None
    if exact_result_digest in traversal.active:
        return None, "dependency_cycle", None
    if policy.trusted_producers is not None and manifest.get("producer") not in policy.trusted_producers:
        return None, "untrusted_producer", None
    invalidation_failure = _effective_invalidated(
        manifest,
        store,
        policy,
        required=manifest["spec_version"] == "oncemesh.result/v1" or depth > 0,
    )
    if invalidation_failure is not None:
        return None, invalidation_failure, None
    selected_validation: dict[str, Any] | None = None
    fresh_until = manifest.get("fresh_until")
    if not ignore_freshness:
        is_fresh = fresh_until is not None and _parse_time(
            fresh_until
        ) >= policy.now.astimezone(timezone.utc)
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
                if trusted and _parse_time(
                    validation["fresh_until"]
                ) >= policy.now.astimezone(timezone.utc):
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

    if manifest["spec_version"] == "oncemesh.result/v1":
        traversal.active.add(exact_result_digest)
        try:
            for dependency in manifest["dependencies"]:
                traversal.edges += 1
                if traversal.edges > policy.max_dependency_count:
                    return None, "dependency_count_exceeded", None
                dependency_manifest, dependency_store, locate_failure = _locate_result(
                    dependency["result_digest"], stores
                )
                if locate_failure is not None:
                    return None, locate_failure, None
                assert dependency_manifest is not None and dependency_store is not None
                _, dependency_failure, _ = _evaluate(
                    dependency_manifest["action_digest"],
                    dependency_manifest,
                    dependency_store,
                    policy,
                    stores=stores,
                    traversal=traversal,
                    depth=depth + 1,
                    ignore_freshness=False,
                )
                if dependency_failure is not None:
                    propagated = (
                        dependency_failure
                        if dependency_failure.startswith("dependency_")
                        else f"dependency_{dependency_failure}"
                    )
                    return None, propagated, None
        finally:
            traversal.active.remove(exact_result_digest)
    return artifacts, None, selected_validation


def reuse(
    action: dict[str, Any],
    stores: Iterable[Store],
    policy: Policy | None = None,
) -> LookupOutcome:
    """Search stores in order and return the first admissible exact hit."""

    selected_policy = policy or Policy()
    requested_digest = action_digest(action)
    selected_stores = tuple(stores)
    rejections: list[str] = []
    for store in selected_stores:
        try:
            candidates = store.candidates(requested_digest)
        except StoreReadError as error:
            rejections.append(f"{store.name}:{error}")
            continue
        for manifest in candidates:
            artifacts, rejection, validation = _evaluate(
                requested_digest,
                manifest,
                store,
                selected_policy,
                stores=selected_stores,
                traversal=_DependencyTraversal(),
            )
            if rejection is not None:
                rejections.append(f"{store.name}:{rejection}")
                continue
            return LookupOutcome(
                True,
                store.name,
                manifest,
                artifacts or {},
                tuple(rejections),
                validation,
            )
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
    selected_stores = tuple(stores)
    rejections: list[str] = []
    for store in selected_stores:
        try:
            candidates = store.candidates(requested_digest)
        except StoreReadError as error:
            rejections.append(f"{store.name}:{error}")
            continue
        for manifest in candidates:
            artifacts, rejection, _ = _evaluate(
                requested_digest,
                manifest,
                store,
                selected_policy,
                stores=selected_stores,
                traversal=_DependencyTraversal(),
                ignore_freshness=True,
            )
            if rejection is not None:
                rejections.append(f"{store.name}:{rejection}")
                continue
            return LookupOutcome(True, store.name, manifest, artifacts or {}, tuple(rejections))
    return LookupOutcome(False, None, None, {}, tuple(rejections))
