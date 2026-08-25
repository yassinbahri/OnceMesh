"""Structured, content-free evaluation metrics for OnceMesh M1."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from threading import Lock
from typing import Any, Protocol


@dataclass(frozen=True)
class EvaluationEvent:
    mode: str
    action_digest: str
    operation: str
    candidate_hit: bool
    tier: str | None
    artifact_match: bool | None
    rejections: tuple[str, ...]
    execution_duration_ms: float
    reusable_bytes: int
    verified_time_saved_ms: float
    verified_cost_saved: float
    lookup_duration_ms: float = 0.0
    evaluation_id: str | None = None
    spec_version: str = "oncemesh.evaluation-event/v0"
    validation_method: str | None = None
    validation_status: int | None = None
    validation_duration_ms: float = 0.0
    validation_recorded: bool = False
    substituted: bool = False
    decision_reason: str | None = None
    kill_switch_active: bool = False
    estimated_substitution_time_saved_ms: float = 0.0
    background_revalidation_scheduled: bool = False
    background_revalidation_coalesced: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class MetricsSink(Protocol):
    def record(self, event: EvaluationEvent) -> None: ...


class InMemoryMetrics:
    def __init__(self) -> None:
        self.events: list[EvaluationEvent] = []
        self._lock = Lock()

    def record(self, event: EvaluationEvent) -> None:
        with self._lock:
            self.events.append(event)

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return summarize(list(self.events))


class JsonlMetrics:
    """Append-only event sink suitable for resumable evaluation runs."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def record(self, event: EvaluationEvent) -> None:
        encoded = json.dumps(event.as_dict(), sort_keys=True, separators=(",", ":")) + "\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8", newline="\n") as output:
                output.write(encoded)
                output.flush()
                os.fsync(output.fileno())


def read_jsonl(path: str | Path, *, evaluation_id: str | None = None) -> list[EvaluationEvent]:
    source = Path(path)
    if not source.exists():
        return []
    raw = source.read_text(encoding="utf-8")
    lines = raw.splitlines()
    events: list[EvaluationEvent] = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
            value["rejections"] = tuple(value.get("rejections", ()))
            event = EvaluationEvent(**value)
        except (json.JSONDecodeError, TypeError) as error:
            if index == len(lines) - 1 and not raw.endswith(("\n", "\r")):
                continue
            raise ValueError(f"invalid metrics JSONL at line {index + 1}") from error
        if evaluation_id is None or event.evaluation_id == evaluation_id:
            events.append(event)
    return events


def _summarize_flat(events: list[EvaluationEvent]) -> dict[str, Any]:
    total = len(events)
    hits = sum(event.candidate_hit for event in events)
    matches = sum(event.artifact_match is True for event in events)
    mismatches = sum(event.artifact_match is False for event in events)
    rejection_counts: Counter[str] = Counter()
    for event in events:
        rejection_counts.update(event.rejections)
    return {
        "evaluations": total,
        "candidate_hits": hits,
        "candidate_hit_rate": hits / total if total else 0.0,
        "verified_matches": matches,
        "verified_match_rate": matches / total if total else 0.0,
        "candidate_match_rate": matches / hits if hits else 0.0,
        "candidate_mismatches": mismatches,
        "rejections": dict(sorted(rejection_counts.items())),
        "lookup_duration_ms": sum(event.lookup_duration_ms for event in events),
        "execution_duration_ms": sum(event.execution_duration_ms for event in events),
        "verified_time_saved_ms": sum(event.verified_time_saved_ms for event in events),
        "verified_cost_saved": sum(event.verified_cost_saved for event in events),
        "reusable_bytes": sum(event.reusable_bytes for event in events),
        "conditional_attempts": sum(event.validation_method == "http.conditional/1" for event in events),
        "conditional_not_modified": sum(event.validation_status == 304 for event in events),
        "validations_recorded": sum(event.validation_recorded for event in events),
        "validation_duration_ms": sum(event.validation_duration_ms for event in events),
        "substitutions": sum(event.substituted for event in events),
        "decision_reasons": dict(
            sorted(Counter(event.decision_reason for event in events if event.decision_reason).items())
        ),
        "kill_switch_activations": sum(event.kill_switch_active for event in events),
        "estimated_substitution_time_saved_ms": sum(
            event.estimated_substitution_time_saved_ms for event in events
        ),
        "background_revalidations_scheduled": sum(
            event.background_revalidation_scheduled for event in events
        ),
        "background_revalidations_coalesced": sum(
            event.background_revalidation_coalesced for event in events
        ),
    }


def summarize(events: list[EvaluationEvent]) -> dict[str, Any]:
    summary = _summarize_flat(events)
    operations: dict[str, list[EvaluationEvent]] = {}
    for event in events:
        operations.setdefault(event.operation, []).append(event)
    summary["by_operation"] = {
        operation: _summarize_flat(operation_events)
        for operation, operation_events in sorted(operations.items())
    }
    return summary
