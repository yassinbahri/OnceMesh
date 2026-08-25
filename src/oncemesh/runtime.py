"""Policy-controlled HTTP execution with narrow conditional substitution."""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from time import perf_counter
from typing import Callable, Mapping

from .adapters import SafeHTTPTransport, execute_http_fetch, response_to_artifacts
from .cache import LookupOutcome, Policy, candidate_for_revalidation, publish_result, reuse
from .canonical import action_digest, manifest_digest
from .conditional import run_conditional_http_shadow
from .metrics import EvaluationEvent, MetricsSink
from .policy import FilePolicyRegistry, OperationPolicy
from .key_registry import FileReceiptKeyRegistry
from .receipt import verify_receipt_for_manifest
from .authorization import authorization_partitions_match, validate_authorization_partition
from .revalidation import RevalidationCoordinator, revalidate_http_candidate
from .shadow import candidate_matches, run_shadow
from .store import Store, StoreReadError

Artifacts = Mapping[str, tuple[bytes, str]]


@dataclass(frozen=True)
class HttpExecutionOutcome:
    artifacts: Artifacts
    substituted: bool
    decision_reason: str
    lookup: LookupOutcome | None


@dataclass(frozen=True)
class DeterministicExecutionOutcome:
    artifacts: Artifacts
    substituted: bool
    decision_reason: str
    lookup: LookupOutcome | None


EXACT_SUBSTITUTION_OPERATIONS = frozenset({"document.pdf-to-text/1"})


def _candidate_outputs(candidate: LookupOutcome) -> dict[str, tuple[bytes, str]]:
    if candidate.manifest is None:
        raise ValueError("candidate has no result manifest")
    media_types = {
        descriptor["name"]: descriptor["media_type"]
        for descriptor in candidate.manifest["artifacts"]
    }
    return {
        name: (data, media_types[name])
        for name, data in candidate.artifacts.items()
    }


def _format_time(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _authorization_failure(
    action: dict,
    policy: OperationPolicy,
    caller_partition: str | None,
) -> str | None:
    action_partition = action.get("vary", {}).get("authorization_partition")
    if policy.authorization_partition == "public":
        if action_partition is not None or caller_partition is not None:
            return "authorization_partition_forbidden"
        return None
    try:
        validate_authorization_partition(action_partition)
    except ValueError:
        return "authorization_partition_invalid"
    if caller_partition is None:
        return "authorization_partition_missing"
    try:
        if not authorization_partitions_match(action_partition, caller_partition):
            return "authorization_partition_mismatch"
    except ValueError:
        return "authorization_partition_invalid"
    return None


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("freshness timestamp must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _latest_trusted_freshness(
    candidate: LookupOutcome,
    stores: list[Store],
    policy: OperationPolicy,
) -> tuple[datetime | None, bool]:
    if candidate.manifest is None:
        return None, False
    boundaries: list[datetime] = []
    manifest_boundary = candidate.manifest.get("fresh_until")
    if manifest_boundary is not None:
        boundaries.append(_parse_utc(manifest_boundary))
    source = next((store for store in stores if store.name == candidate.tier), None)
    if source is None:
        return max(boundaries) if boundaries else None, False
    try:
        validations = source.validations(manifest_digest(candidate.manifest))
    except StoreReadError:
        return None, True
    for validation in validations:
        if validation["producer"] in policy.trusted_validation_producers:
            boundaries.append(_parse_utc(validation["fresh_until"]))
    return (max(boundaries) if boundaries else None), False


def execute_deterministic_with_policy(
    action: dict,
    stores: list[Store],
    execute: Callable[[], Artifacts],
    metrics: MetricsSink,
    registry: FilePolicyRegistry,
    *,
    key_registry: FileReceiptKeyRegistry | None = None,
    caller_authorization_partition: str | None = None,
    publish_to: Store | None,
    producer: str,
    freshness_seconds: int = 86400,
    estimated_execution_cost: float = 0.0,
    estimated_execution_time_ms: float = 0.0,
    now: datetime | None = None,
    evaluation_id: str | None = None,
) -> DeterministicExecutionOutcome:
    """Substitute an exact, fresh deterministic result only when explicitly authorized."""

    operation_key = f"{action['operation']['name']}/{action['operation']['version']}"
    if operation_key not in EXACT_SUBSTITUTION_OPERATIONS:
        raise ValueError("operation is not approved for exact deterministic substitution")
    if freshness_seconds <= 0:
        raise ValueError("freshness_seconds must be positive")
    evaluation_time = now or datetime.now(timezone.utc)
    resolution = registry.resolve(operation_key)
    selected_policy = resolution.policy
    ttl = min(
        freshness_seconds,
        selected_policy.max_validation_ttl_seconds if selected_policy else freshness_seconds,
    )
    fresh_until = evaluation_time + timedelta(seconds=ttl)

    def execute_and_record(reason: str, lookup: LookupOutcome | None = None) -> DeterministicExecutionOutcome:
        started = perf_counter()
        artifacts = dict(execute())
        duration_ms = (perf_counter() - started) * 1000
        if publish_to is not None:
            publish_result(
                publish_to,
                action,
                artifacts,
                producer=producer,
                produced_at=evaluation_time,
                fresh_until=fresh_until,
            )
        metrics.record(
            EvaluationEvent(
                mode="execute",
                action_digest=action_digest(action),
                operation=action["operation"]["name"],
                candidate_hit=bool(lookup and lookup.hit),
                tier=lookup.tier if lookup else None,
                artifact_match=candidate_matches(artifacts, lookup) if lookup else None,
                rejections=lookup.rejections if lookup else (),
                execution_duration_ms=duration_ms,
                reusable_bytes=0,
                verified_time_saved_ms=0.0,
                verified_cost_saved=0.0,
                evaluation_id=evaluation_id,
                decision_reason=reason,
                kill_switch_active=resolution.kill_switch_active,
            )
        )
        return DeterministicExecutionOutcome(artifacts, False, reason, lookup)

    if selected_policy is None:
        return execute_and_record(resolution.reason)
    authorization_failure = _authorization_failure(
        action, selected_policy, caller_authorization_partition
    )
    if authorization_failure is not None:
        return execute_and_record(authorization_failure)
    trust_policy = Policy(
        now=evaluation_time,
        trusted_producers=selected_policy.trusted_result_producers,
        trusted_validation_producers=selected_policy.trusted_validation_producers,
    )
    if selected_policy.mode == "shadow":
        shadow = run_shadow(
            action,
            stores,
            execute,
            metrics,
            policy=trust_policy,
            estimated_execution_cost=estimated_execution_cost,
            publish_to=publish_to,
            producer=producer,
            fresh_until=fresh_until,
            now=evaluation_time,
            evaluation_id=evaluation_id,
        )
        return DeterministicExecutionOutcome(shadow.artifacts, False, "shadow", shadow.lookup)
    if selected_policy.mode != "exact-substitute":
        return execute_and_record("policy_mode_incompatible")

    lookup_started = perf_counter()
    candidate = reuse(action, stores, trust_policy)
    lookup_duration_ms = (perf_counter() - lookup_started) * 1000
    if not candidate.hit or candidate.manifest is None:
        return execute_and_record("candidate_missing", candidate)
    if candidate.tier not in selected_policy.allowed_tiers:
        return execute_and_record("tier_denied", candidate)
    if selected_policy.receipt_requirement == "required":
        receipt_failure = _required_receipt_failure(
            candidate, stores, selected_policy, key_registry
        )
        if receipt_failure is not None:
            return execute_and_record(receipt_failure, candidate)

    artifacts = _candidate_outputs(candidate)
    reusable_bytes = sum(len(value) for value in candidate.artifacts.values())
    metrics.record(
        EvaluationEvent(
            mode="substitute",
            action_digest=action_digest(action),
            operation=action["operation"]["name"],
            candidate_hit=True,
            tier=candidate.tier,
            artifact_match=None,
            rejections=candidate.rejections,
            execution_duration_ms=0.0,
            reusable_bytes=reusable_bytes,
            verified_time_saved_ms=0.0,
            verified_cost_saved=estimated_execution_cost,
            lookup_duration_ms=lookup_duration_ms,
            evaluation_id=evaluation_id,
            substituted=True,
            decision_reason="exact_fresh_hit",
            estimated_substitution_time_saved_ms=max(
                estimated_execution_time_ms - lookup_duration_ms, 0.0
            ),
        )
    )
    return DeterministicExecutionOutcome(artifacts, True, "exact_fresh_hit", candidate)


def _required_receipt_failure(
    candidate: LookupOutcome,
    stores: list[Store],
    policy: OperationPolicy,
    key_registry: FileReceiptKeyRegistry | None,
) -> str | None:
    if key_registry is None:
        return "receipt_registry_missing"
    if candidate.manifest is None:
        return "receipt_missing"
    source = next((store for store in stores if store.name == candidate.tier), None)
    if source is None:
        return "receipt_missing"
    try:
        receipts = source.receipts(manifest_digest(candidate.manifest))
    except (StoreReadError, ValueError):
        return "receipt_invalid"
    if not receipts:
        return "receipt_missing"

    failures: list[str] = []
    for receipt in receipts:
        signature = receipt.get("signature")
        if not isinstance(signature, dict):
            failures.append("receipt_missing")
            continue
        key_id = signature.get("key_id")
        if key_id not in policy.trusted_receipt_keys:
            failures.append("receipt_key_untrusted")
            continue
        resolution = key_registry.resolve(key_id, candidate.manifest["producer"])
        if resolution.reason == "receipt_registry_error":
            return resolution.reason
        if resolution.key is None:
            failures.append(resolution.reason)
            continue
        try:
            verified = verify_receipt_for_manifest(
                receipt, candidate.manifest, resolution.key.public_key
            )
        except ValueError:
            verified = False
        if verified:
            return None
        failures.append("receipt_invalid")

    priority = (
        "receipt_invalid",
        "receipt_key_revoked",
        "receipt_producer_denied",
        "receipt_key_unknown",
        "receipt_key_untrusted",
        "receipt_missing",
    )
    return next((reason for reason in priority if reason in failures), "receipt_invalid")


def _execute_full(
    action: dict,
    transport: SafeHTTPTransport,
    metrics: MetricsSink,
    *,
    reason: str,
    publish_to: Store | None,
    producer: str,
    now: datetime,
    fresh_until: datetime,
    evaluation_id: str | None,
    lookup: LookupOutcome | None = None,
    kill_switch_active: bool = False,
) -> HttpExecutionOutcome:
    started = perf_counter()
    artifacts = execute_http_fetch(action, transport)
    duration_ms = (perf_counter() - started) * 1000
    if publish_to is not None:
        publish_result(
            publish_to,
            action,
            artifacts,
            producer=producer,
            produced_at=now,
            fresh_until=fresh_until,
        )
    metrics.record(
        EvaluationEvent(
            mode="execute",
            action_digest=action_digest(action),
            operation=action["operation"]["name"],
            candidate_hit=bool(lookup and lookup.hit),
            tier=lookup.tier if lookup else None,
            artifact_match=candidate_matches(artifacts, lookup) if lookup else None,
            rejections=lookup.rejections if lookup else (),
            execution_duration_ms=duration_ms,
            reusable_bytes=0,
            verified_time_saved_ms=0.0,
            verified_cost_saved=0.0,
            evaluation_id=evaluation_id,
            decision_reason=reason,
            kill_switch_active=kill_switch_active,
        )
    )
    return HttpExecutionOutcome(artifacts, False, reason, lookup)


def execute_http_with_policy(
    action: dict,
    stores: list[Store],
    transport: SafeHTTPTransport,
    metrics: MetricsSink,
    registry: FilePolicyRegistry,
    *,
    publish_to: Store | None,
    producer: str,
    validation_ttl_seconds: int = 3600,
    estimated_execution_cost: float = 0.0,
    estimated_execution_time_ms: float = 0.0,
    now: datetime | None = None,
    evaluation_id: str | None = None,
    caller_authorization_partition: str | None = None,
    revalidation_coordinator: RevalidationCoordinator | None = None,
) -> HttpExecutionOutcome:
    """Execute or conditionally substitute according to the current policy file."""

    if action.get("operation") != {"name": "http.fetch", "version": "1"}:
        raise ValueError("policy runtime currently supports http.fetch/1 only")
    if validation_ttl_seconds <= 0:
        raise ValueError("validation_ttl_seconds must be positive")
    evaluation_time = now or datetime.now(timezone.utc)
    operation_key = f"{action['operation']['name']}/{action['operation']['version']}"
    resolution = registry.resolve(operation_key)
    selected_policy = resolution.policy
    ttl = validation_ttl_seconds
    if selected_policy is not None:
        ttl = min(ttl, selected_policy.max_validation_ttl_seconds)
    fresh_until = evaluation_time + timedelta(seconds=ttl)

    if selected_policy is None:
        return _execute_full(
            action,
            transport,
            metrics,
            reason=resolution.reason,
            publish_to=publish_to,
            producer=producer,
            now=evaluation_time,
            fresh_until=fresh_until,
            evaluation_id=evaluation_id,
            kill_switch_active=resolution.kill_switch_active,
        )

    authorization_failure = _authorization_failure(
        action, selected_policy, caller_authorization_partition
    )
    if authorization_failure is not None:
        return _execute_full(
            action,
            transport,
            metrics,
            reason=authorization_failure,
            publish_to=publish_to,
            producer=producer,
            now=evaluation_time,
            fresh_until=fresh_until,
            evaluation_id=evaluation_id,
        )

    trust_policy = Policy(
        now=evaluation_time,
        trusted_producers=selected_policy.trusted_result_producers,
        trusted_validation_producers=selected_policy.trusted_validation_producers,
    )
    if selected_policy.mode == "shadow":
        outcome = run_conditional_http_shadow(
            action,
            stores,
            transport,
            metrics,
            policy=trust_policy,
            estimated_execution_cost=estimated_execution_cost,
            publish_to=publish_to,
            producer=producer,
            fresh_until=fresh_until,
            now=evaluation_time,
            evaluation_id=evaluation_id,
            decision_reason="shadow",
        )
        return HttpExecutionOutcome(outcome.artifacts, False, "shadow", outcome.lookup)

    if selected_policy.mode == "stale-while-revalidate":
        lookup_started = perf_counter()
        candidate = candidate_for_revalidation(action, stores, trust_policy)
        lookup_duration_ms = (perf_counter() - lookup_started) * 1000
        if not candidate.hit or candidate.manifest is None:
            return _execute_full(
                action, transport, metrics, reason="candidate_missing", publish_to=publish_to,
                producer=producer, now=evaluation_time, fresh_until=fresh_until,
                evaluation_id=evaluation_id, lookup=candidate,
            )
        if candidate.tier not in selected_policy.allowed_tiers:
            return _execute_full(
                action, transport, metrics, reason="tier_denied", publish_to=publish_to,
                producer=producer, now=evaluation_time, fresh_until=fresh_until,
                evaluation_id=evaluation_id, lookup=candidate,
            )
        boundary, validation_read_failed = _latest_trusted_freshness(
            candidate, stores, selected_policy
        )
        if validation_read_failed:
            reason = "stale_validation_read_failed"
        elif boundary is None:
            reason = "stale_freshness_missing"
        else:
            stale_seconds = (evaluation_time - boundary).total_seconds()
            if stale_seconds <= 0:
                artifacts = _candidate_outputs(candidate)
                metrics.record(EvaluationEvent(
                    mode="substitute", action_digest=action_digest(action), operation="http.fetch",
                    candidate_hit=True, tier=candidate.tier, artifact_match=None,
                    rejections=candidate.rejections, execution_duration_ms=0.0,
                    reusable_bytes=sum(len(value) for value in candidate.artifacts.values()),
                    verified_time_saved_ms=0.0, verified_cost_saved=estimated_execution_cost,
                    lookup_duration_ms=lookup_duration_ms, evaluation_id=evaluation_id,
                    substituted=True, decision_reason="fresh_hit",
                    estimated_substitution_time_saved_ms=max(
                        estimated_execution_time_ms - lookup_duration_ms, 0.0
                    ),
                ))
                return HttpExecutionOutcome(artifacts, True, "fresh_hit", candidate)
            reason = "stale_window_exceeded" if stale_seconds > selected_policy.max_stale_seconds else ""
        if reason:
            return _execute_full(
                action, transport, metrics, reason=reason, publish_to=publish_to,
                producer=producer, now=evaluation_time, fresh_until=fresh_until,
                evaluation_id=evaluation_id, lookup=candidate,
            )
        try:
            metadata = json.loads(candidate.artifacts["metadata"].decode("utf-8"))
            etag = metadata.get("etag")
            last_modified = metadata.get("last_modified")
        except (KeyError, UnicodeError, json.JSONDecodeError):
            etag = last_modified = None
        if not etag and not last_modified:
            return _execute_full(
                action, transport, metrics, reason="validator_missing", publish_to=publish_to,
                producer=producer, now=evaluation_time, fresh_until=fresh_until,
                evaluation_id=evaluation_id, lookup=candidate,
            )
        if producer not in selected_policy.trusted_validation_producers:
            return _execute_full(
                action, transport, metrics, reason="validator_untrusted", publish_to=publish_to,
                producer=producer, now=evaluation_time, fresh_until=fresh_until,
                evaluation_id=evaluation_id, lookup=candidate,
            )
        if producer not in selected_policy.trusted_result_producers:
            return _execute_full(
                action, transport, metrics, reason="refresh_producer_untrusted", publish_to=publish_to,
                producer=producer, now=evaluation_time, fresh_until=fresh_until,
                evaluation_id=evaluation_id, lookup=candidate,
            )
        if revalidation_coordinator is None:
            return _execute_full(
                action, transport, metrics, reason="revalidation_scheduler_missing", publish_to=publish_to,
                producer=producer, now=evaluation_time, fresh_until=fresh_until,
                evaluation_id=evaluation_id, lookup=candidate,
            )
        if publish_to is None:
            return _execute_full(
                action, transport, metrics, reason="revalidation_publish_store_missing", publish_to=None,
                producer=producer, now=evaluation_time, fresh_until=fresh_until,
                evaluation_id=evaluation_id, lookup=candidate,
            )
        try:
            background_action = deepcopy(action)
            background_candidate = deepcopy(candidate)
            scheduled = revalidation_coordinator.submit(
                action_digest(action),
                lambda: revalidate_http_candidate(
                    background_action, background_candidate, transport, metrics, publish_to=publish_to,
                    producer=producer, validation_ttl_seconds=ttl,
                    evaluation_id=evaluation_id,
                ),
            )
        except Exception:
            return _execute_full(
                action, transport, metrics, reason="revalidation_schedule_failed", publish_to=publish_to,
                producer=producer, now=evaluation_time, fresh_until=fresh_until,
                evaluation_id=evaluation_id, lookup=candidate,
            )
        artifacts = _candidate_outputs(candidate)
        metrics.record(EvaluationEvent(
            mode="substitute", action_digest=action_digest(action), operation="http.fetch",
            candidate_hit=True, tier=candidate.tier, artifact_match=None,
            rejections=candidate.rejections, execution_duration_ms=0.0,
            reusable_bytes=sum(len(value) for value in candidate.artifacts.values()),
            verified_time_saved_ms=0.0, verified_cost_saved=0.0,
            lookup_duration_ms=lookup_duration_ms, evaluation_id=evaluation_id,
            substituted=True, decision_reason="stale_while_revalidate",
            estimated_substitution_time_saved_ms=max(
                estimated_execution_time_ms - lookup_duration_ms, 0.0
            ),
            background_revalidation_scheduled=scheduled,
            background_revalidation_coalesced=not scheduled,
        ))
        return HttpExecutionOutcome(artifacts, True, "stale_while_revalidate", candidate)

    lookup_started = perf_counter()
    candidate = candidate_for_revalidation(action, stores, trust_policy)
    lookup_duration_ms = (perf_counter() - lookup_started) * 1000
    if not candidate.hit or candidate.manifest is None:
        return _execute_full(
            action,
            transport,
            metrics,
            reason="candidate_missing",
            publish_to=publish_to,
            producer=producer,
            now=evaluation_time,
            fresh_until=fresh_until,
            evaluation_id=evaluation_id,
            lookup=candidate,
        )
    if candidate.tier not in selected_policy.allowed_tiers:
        return _execute_full(
            action,
            transport,
            metrics,
            reason="tier_denied",
            publish_to=publish_to,
            producer=producer,
            now=evaluation_time,
            fresh_until=fresh_until,
            evaluation_id=evaluation_id,
            lookup=candidate,
        )
    if producer not in selected_policy.trusted_validation_producers:
        return _execute_full(
            action,
            transport,
            metrics,
            reason="validator_untrusted",
            publish_to=publish_to,
            producer=producer,
            now=evaluation_time,
            fresh_until=fresh_until,
            evaluation_id=evaluation_id,
            lookup=candidate,
        )
    try:
        metadata = json.loads(candidate.artifacts["metadata"].decode("utf-8"))
        etag = metadata.get("etag")
        last_modified = metadata.get("last_modified")
    except (KeyError, UnicodeError, json.JSONDecodeError):
        etag = last_modified = None
    if not etag and not last_modified:
        return _execute_full(
            action,
            transport,
            metrics,
            reason="validator_missing",
            publish_to=publish_to,
            producer=producer,
            now=evaluation_time,
            fresh_until=fresh_until,
            evaluation_id=evaluation_id,
            lookup=candidate,
        )

    inputs = action["inputs"]
    config = action["executor"]["config"]
    validation_started = perf_counter()
    response = transport.conditional_get(
        inputs["url"],
        inputs["accept"],
        config["follow_redirects"],
        config["max_bytes"],
        etag=etag,
        last_modified=last_modified,
    )
    validation_duration_ms = (perf_counter() - validation_started) * 1000
    if response.status == 200:
        artifacts = response_to_artifacts(action, response)
        if publish_to is not None:
            publish_result(
                publish_to,
                action,
                artifacts,
                producer=producer,
                produced_at=evaluation_time,
                fresh_until=fresh_until,
            )
        metrics.record(
            EvaluationEvent(
                mode="execute",
                action_digest=action_digest(action),
                operation="http.fetch",
                candidate_hit=True,
                tier=candidate.tier,
                artifact_match=candidate_matches(artifacts, candidate),
                rejections=candidate.rejections,
                execution_duration_ms=validation_duration_ms,
                reusable_bytes=0,
                verified_time_saved_ms=0.0,
                verified_cost_saved=0.0,
                lookup_duration_ms=lookup_duration_ms,
                evaluation_id=evaluation_id,
                validation_method="http.conditional/1",
                validation_status=200,
                validation_duration_ms=validation_duration_ms,
                decision_reason="source_changed",
            )
        )
        return HttpExecutionOutcome(artifacts, False, "source_changed", candidate)
    if response.status != 304:
        raise ValueError(f"unexpected conditional response status {response.status}")

    if publish_to is not None:
        publish_to.put_validation(
            {
                "spec_version": "oncemesh.validation/v0",
                "result_digest": manifest_digest(candidate.manifest),
                "validated_at": _format_time(evaluation_time),
                "fresh_until": _format_time(fresh_until),
                "producer": producer,
                "method": {
                    "name": "http.conditional",
                    "version": "1",
                    "status": 304,
                    "etag": etag,
                    "last_modified": last_modified,
                },
            }
        )
    selected_artifacts = _candidate_outputs(candidate)
    reusable_bytes = sum(len(value) for value in candidate.artifacts.values())
    estimated_saved = max(
        estimated_execution_time_ms - lookup_duration_ms - validation_duration_ms, 0.0
    )
    metrics.record(
        EvaluationEvent(
            mode="substitute",
            action_digest=action_digest(action),
            operation="http.fetch",
            candidate_hit=True,
            tier=candidate.tier,
            artifact_match=None,
            rejections=candidate.rejections,
            execution_duration_ms=0.0,
            reusable_bytes=reusable_bytes,
            verified_time_saved_ms=0.0,
            verified_cost_saved=estimated_execution_cost,
            lookup_duration_ms=lookup_duration_ms,
            evaluation_id=evaluation_id,
            validation_method="http.conditional/1",
            validation_status=304,
            validation_duration_ms=validation_duration_ms,
            validation_recorded=publish_to is not None,
            substituted=True,
            decision_reason="conditional_304",
            estimated_substitution_time_saved_ms=estimated_saved,
        )
    )
    return HttpExecutionOutcome(selected_artifacts, True, "conditional_304", candidate)
