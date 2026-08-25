"""Shadow-only conditional HTTP source validation."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from time import perf_counter

from .adapters import SafeHTTPTransport, execute_http_fetch, response_to_artifacts
from .cache import Policy, candidate_for_revalidation, publish_result
from .canonical import action_digest, manifest_digest
from .metrics import EvaluationEvent, MetricsSink
from .shadow import ShadowOutcome, candidate_matches, run_shadow
from .store import Store


def _format_time(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def run_conditional_http_shadow(
    action: dict,
    stores: list[Store],
    transport: SafeHTTPTransport,
    metrics: MetricsSink,
    *,
    policy: Policy | None = None,
    estimated_execution_cost: float = 0.0,
    publish_to: Store | None = None,
    producer: str = "local:conditional-shadow",
    fresh_until: datetime,
    now: datetime | None = None,
    evaluation_id: str | None = None,
    decision_reason: str = "shadow",
) -> ShadowOutcome:
    """Attempt conditional validation, then still obtain and compare full output."""

    evaluation_time = now or datetime.now(timezone.utc)
    lookup_started = perf_counter()
    candidate = candidate_for_revalidation(action, stores, policy or Policy(now=evaluation_time))
    lookup_duration_ms = (perf_counter() - lookup_started) * 1000
    if not candidate.hit or candidate.manifest is None or "metadata" not in candidate.artifacts:
        return run_shadow(
            action,
            stores,
            lambda: execute_http_fetch(action, transport),
            metrics,
            policy=policy,
            estimated_execution_cost=estimated_execution_cost,
            publish_to=publish_to,
            producer=producer,
            fresh_until=fresh_until,
            now=evaluation_time,
            evaluation_id=evaluation_id,
        )

    metadata = json.loads(candidate.artifacts["metadata"].decode("utf-8"))
    etag = metadata.get("etag")
    last_modified = metadata.get("last_modified")
    if not etag and not last_modified:
        return run_shadow(
            action,
            stores,
            lambda: execute_http_fetch(action, transport),
            metrics,
            policy=policy,
            estimated_execution_cost=estimated_execution_cost,
            publish_to=publish_to,
            producer=producer,
            fresh_until=fresh_until,
            now=evaluation_time,
            evaluation_id=evaluation_id,
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

    execution_started = perf_counter()
    if response.status == 304:
        actual = execute_http_fetch(action, transport)
    elif response.status == 200:
        actual = response_to_artifacts(action, response)
    else:
        raise ValueError(f"unexpected conditional response status {response.status}")
    execution_duration_ms = (perf_counter() - execution_started) * 1000
    match = candidate_matches(actual, candidate)
    validation_recorded = response.status == 304 and match is True and publish_to is not None

    if validation_recorded:
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
    elif publish_to is not None:
        publish_result(
            publish_to,
            action,
            actual,
            producer=producer,
            produced_at=evaluation_time,
            fresh_until=fresh_until,
        )

    verified = response.status == 304 and match is True
    reusable_bytes = sum(len(data) for data, _ in actual.values()) if verified else 0
    metrics.record(
        EvaluationEvent(
            mode="shadow",
            action_digest=action_digest(action),
            operation=action["operation"]["name"],
            candidate_hit=True,
            tier=candidate.tier,
            artifact_match=match,
            rejections=candidate.rejections,
            execution_duration_ms=execution_duration_ms,
            reusable_bytes=reusable_bytes,
            verified_time_saved_ms=max(
                execution_duration_ms - lookup_duration_ms - validation_duration_ms, 0.0
            )
            if verified
            else 0.0,
            verified_cost_saved=estimated_execution_cost if verified else 0.0,
            lookup_duration_ms=lookup_duration_ms,
            evaluation_id=evaluation_id,
            validation_method="http.conditional/1",
            validation_status=response.status,
            validation_duration_ms=validation_duration_ms,
            validation_recorded=validation_recorded,
            decision_reason=decision_reason,
        )
    )
    return ShadowOutcome(actual, candidate, match, execution_duration_ms)
