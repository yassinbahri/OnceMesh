"""Single-flight coordination and guarded background HTTP revalidation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from threading import Condition, Lock
from time import perf_counter
from typing import Callable, Protocol

from .adapters import SafeHTTPTransport, response_to_artifacts
from .cache import LookupOutcome, publish_result
from .canonical import action_digest, manifest_digest
from .metrics import EvaluationEvent, MetricsSink
from .shadow import candidate_matches
from .store import Store


class RevalidationCoordinator(Protocol):
    def submit(self, key: str, work: Callable[[], None]) -> bool:
        """Return true when scheduled, false when coalesced with existing work."""
        ...


class SingleFlightRevalidator:
    def __init__(self, *, max_workers: int = 4) -> None:
        if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers <= 0:
            raise ValueError("max_workers must be a positive integer")
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="oncemesh-swr")
        self._lock = Lock()
        self._idle = Condition(self._lock)
        self._inflight: set[str] = set()

    def submit(self, key: str, work: Callable[[], None]) -> bool:
        with self._lock:
            if key in self._inflight:
                return False
            self._inflight.add(key)

        def guarded() -> None:
            try:
                work()
            finally:
                with self._lock:
                    self._inflight.discard(key)
                    self._idle.notify_all()

        try:
            self._executor.submit(guarded)
        except BaseException:
            with self._lock:
                self._inflight.discard(key)
                self._idle.notify_all()
            raise
        return True

    def wait_for_idle(self, timeout: float | None = None) -> bool:
        with self._lock:
            return self._idle.wait_for(lambda: not self._inflight, timeout=timeout)

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def revalidate_http_candidate(
    action: dict,
    candidate: LookupOutcome,
    transport: SafeHTTPTransport,
    metrics: MetricsSink,
    *,
    publish_to: Store,
    producer: str,
    validation_ttl_seconds: int,
    evaluation_id: str | None = None,
    clock: Callable[[], datetime] | None = None,
) -> None:
    """Run one conditional refresh and publish only authoritative outcomes."""
    started = perf_counter()
    status: int | None = None
    recorded = False
    reason = "background_failed"
    artifact_match = None
    try:
        if candidate.manifest is None:
            raise ValueError("background candidate has no manifest")
        metadata = json.loads(candidate.artifacts["metadata"].decode("utf-8"))
        etag = metadata.get("etag")
        last_modified = metadata.get("last_modified")
        if not etag and not last_modified:
            raise ValueError("background candidate has no validator")
        inputs = action["inputs"]
        config = action["executor"]["config"]
        response = transport.conditional_get(
            inputs["url"], inputs["accept"], config["follow_redirects"], config["max_bytes"],
            etag=etag, last_modified=last_modified,
        )
        status = response.status
        observed_at = (clock or (lambda: datetime.now(timezone.utc)))()
        fresh_until = observed_at + timedelta(seconds=validation_ttl_seconds)
        if status == 304:
            publish_to.put_validation({
                "spec_version": "oncemesh.validation/v0",
                "result_digest": manifest_digest(candidate.manifest),
                "validated_at": _format_time(observed_at),
                "fresh_until": _format_time(fresh_until),
                "producer": producer,
                "method": {
                    "name": "http.conditional", "version": "1", "status": 304,
                    "etag": etag, "last_modified": last_modified,
                },
            })
            recorded = True
            reason = "background_not_modified"
        elif status == 200:
            artifacts = response_to_artifacts(action, response)
            artifact_match = candidate_matches(artifacts, candidate)
            publish_result(
                publish_to, action, artifacts, producer=producer,
                produced_at=observed_at, fresh_until=fresh_until,
            )
            reason = "background_source_changed"
        else:
            raise ValueError(f"unexpected background status {status}")
    except Exception:
        reason = "background_failed"
    duration_ms = (perf_counter() - started) * 1000
    metrics.record(EvaluationEvent(
        mode="background-revalidate",
        action_digest=action_digest(action),
        operation="http.fetch",
        candidate_hit=True,
        tier=candidate.tier,
        artifact_match=artifact_match,
        rejections=candidate.rejections,
        execution_duration_ms=duration_ms,
        reusable_bytes=0,
        verified_time_saved_ms=0.0,
        verified_cost_saved=0.0,
        evaluation_id=evaluation_id,
        validation_method="http.conditional/1",
        validation_status=status,
        validation_duration_ms=duration_ms,
        validation_recorded=recorded,
        decision_reason=reason,
    ))
