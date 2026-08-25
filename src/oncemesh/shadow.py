"""Shadow evaluation: measure candidate quality without substituting output."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Callable, Mapping

from .cache import LookupOutcome, Policy, publish_result, reuse
from .canonical import action_digest
from .metrics import EvaluationEvent, MetricsSink
from .store import Store

Artifacts = Mapping[str, tuple[bytes, str]]


@dataclass(frozen=True)
class ShadowOutcome:
    artifacts: Artifacts
    lookup: LookupOutcome
    artifact_match: bool | None
    execution_duration_ms: float


def candidate_matches(actual: Artifacts, lookup: LookupOutcome) -> bool | None:
    if not lookup.hit or lookup.manifest is None:
        return None
    descriptors = {
        descriptor["name"]: descriptor["media_type"]
        for descriptor in lookup.manifest["artifacts"]
    }
    if set(actual) != set(lookup.artifacts) or set(actual) != set(descriptors):
        return False
    return all(
        actual[name][0] == lookup.artifacts[name] and actual[name][1] == descriptors[name]
        for name in actual
    )


def run_shadow(
    action: dict,
    stores: list[Store],
    execute: Callable[[], Artifacts],
    metrics: MetricsSink,
    *,
    policy: Policy | None = None,
    estimated_execution_cost: float = 0.0,
    publish_to: Store | None = None,
    producer: str = "local:shadow",
    fresh_until: datetime | None = None,
    now: datetime | None = None,
    evaluation_id: str | None = None,
) -> ShadowOutcome:
    """Look up a candidate, execute regardless, compare, record, then optionally publish."""

    evaluation_time = now or datetime.now(timezone.utc)
    lookup_started = perf_counter()
    lookup = reuse(action, stores, policy or Policy(now=evaluation_time))
    lookup_duration_ms = (perf_counter() - lookup_started) * 1000
    started = perf_counter()
    actual = dict(execute())
    duration_ms = (perf_counter() - started) * 1000
    match = candidate_matches(actual, lookup)

    verified = match is True
    reusable_bytes = sum(len(data) for data, _ in actual.values()) if verified else 0
    metrics.record(
        EvaluationEvent(
            mode="shadow",
            action_digest=action_digest(action),
            operation=action["operation"]["name"],
            candidate_hit=lookup.hit,
            tier=lookup.tier,
            artifact_match=match,
            rejections=lookup.rejections,
            execution_duration_ms=duration_ms,
            reusable_bytes=reusable_bytes,
            verified_time_saved_ms=max(duration_ms - lookup_duration_ms, 0.0) if verified else 0.0,
            verified_cost_saved=estimated_execution_cost if verified else 0.0,
            lookup_duration_ms=lookup_duration_ms,
            evaluation_id=evaluation_id,
        )
    )

    if publish_to is not None:
        publish_result(
            publish_to,
            action,
            actual,
            producer=producer,
            produced_at=evaluation_time,
            fresh_until=fresh_until,
        )
    return ShadowOutcome(actual, lookup, match, duration_ms)
