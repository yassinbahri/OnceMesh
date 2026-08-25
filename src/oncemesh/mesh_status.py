"""Bounded independent reachability observations for public mesh entries."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any
from urllib.parse import urlsplit

from .adapters.safe_http import SafeHTTPTransport
from .discovery import MESH_STATUSES, validate_public_mesh_directory
from .document_validation import exact_keys as _exact_keys
from .document_validation import format_canonical_utc as _canonical_utc
from .document_validation import parse_canonical_utc as _parse_utc

PUBLIC_MESH_STATUS_VERSION = "oncemesh.public-mesh-status/v0"
STATUS_PATH = "/v0/availability"
ACTIVE_REGISTRY_STATUSES = frozenset({"listed", "observed"})
EXPECTED_HTTP_STATUSES = frozenset({200, 401})
STATUS_STATES = frozenset({"up", "degraded", "down", "not_checked"})
MAX_ACTIVE_MESHES = 500
MAX_CONCURRENCY = 8
MAX_RESPONSE_BYTES = 4096

StatusProbe = Callable[[str, float], tuple[int, int]]
Clock = Callable[[], datetime]


def _default_probe(url: str, timeout_seconds: float) -> tuple[int, int]:
    host = urlsplit(url).hostname
    if not host:
        raise ValueError("mesh status URL has no host")
    transport = SafeHTTPTransport({host}, timeout_seconds=timeout_seconds, max_redirects=0)
    started = time.perf_counter_ns()
    response = transport.probe(url, "application/json", MAX_RESPONSE_BYTES)
    elapsed_ms = max(0, round((time.perf_counter_ns() - started) / 1_000_000))
    if response.final_url != url:
        raise ValueError("mesh status probe redirected")
    return response.status, elapsed_ms


def _observation(
    mesh: dict[str, Any],
    *,
    checked_at: str,
    timeout_seconds: float,
    probe: StatusProbe,
) -> dict[str, Any]:
    if mesh["status"] not in ACTIVE_REGISTRY_STATUSES:
        return {
            "peer_id": mesh["peer_id"],
            "registry_status": mesh["status"],
            "state": "not_checked",
            "checked_at": None,
            "response_time_ms": None,
            "http_status": None,
            "detail": "registry-inactive",
        }
    target = f"{mesh['endpoint'].rstrip('/')}{STATUS_PATH}"
    try:
        http_status, response_time_ms = probe(target, timeout_seconds)
    except Exception:  # The public snapshot intentionally records no exception detail.
        return {
            "peer_id": mesh["peer_id"],
            "registry_status": mesh["status"],
            "state": "down",
            "checked_at": checked_at,
            "response_time_ms": None,
            "http_status": None,
            "detail": "network-failure",
        }
    expected = http_status in EXPECTED_HTTP_STATUSES
    return {
        "peer_id": mesh["peer_id"],
        "registry_status": mesh["status"],
        "state": "up" if expected else "degraded",
        "checked_at": checked_at,
        "response_time_ms": response_time_ms,
        "http_status": http_status,
        "detail": "expected-protocol-response" if expected else "unexpected-http-response",
    }


def generate_public_mesh_status(
    directory: dict[str, Any],
    *,
    probe: StatusProbe | None = None,
    clock: Clock | None = None,
    timeout_seconds: float = 5.0,
    schedule_minutes: int = 30,
    runner_region: str = "github-hosted",
    concurrency: int = MAX_CONCURRENCY,
) -> dict[str, Any]:
    meshes = validate_public_mesh_directory(directory)
    active_count = sum(mesh["status"] in ACTIVE_REGISTRY_STATUSES for mesh in meshes)
    if active_count > MAX_ACTIVE_MESHES:
        raise ValueError(f"active mesh count exceeds {MAX_ACTIVE_MESHES}")
    if timeout_seconds < 0.1 or timeout_seconds > 30:
        raise ValueError("status timeout must be between 0.1 and 30 seconds")
    if schedule_minutes < 5 or schedule_minutes > 1440:
        raise ValueError("status schedule must be between 5 and 1440 minutes")
    if concurrency < 1 or concurrency > MAX_CONCURRENCY:
        raise ValueError(f"status concurrency must be between 1 and {MAX_CONCURRENCY}")
    if not runner_region or len(runner_region) > 80:
        raise ValueError("runner region must be a bounded non-empty string")
    selected_clock = clock or (lambda: datetime.now(timezone.utc))
    selected_probe = probe or _default_probe
    checked_at = _canonical_utc(selected_clock())
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        observations = tuple(
            executor.map(
                lambda mesh: _observation(
                    mesh,
                    checked_at=checked_at,
                    timeout_seconds=timeout_seconds,
                    probe=selected_probe,
                ),
                meshes,
            )
        )
    snapshot = {
        "spec_version": PUBLIC_MESH_STATUS_VERSION,
        "generated_at": _canonical_utc(selected_clock()),
        "monitor": {
            "name": "OnceMesh directory monitor",
            "method": "unauthenticated-https",
            "path": STATUS_PATH,
            "schedule_minutes": schedule_minutes,
            "timeout_ms": round(timeout_seconds * 1000),
            "runner_region": runner_region,
        },
        "meshes": list(observations),
    }
    validate_public_mesh_status(snapshot, directory)
    return snapshot


def validate_public_mesh_status(snapshot: Any, directory: dict[str, Any]) -> None:
    meshes = validate_public_mesh_directory(directory)
    _exact_keys(snapshot, {"spec_version", "generated_at", "monitor", "meshes"}, "status snapshot")
    if snapshot["spec_version"] != PUBLIC_MESH_STATUS_VERSION:
        raise ValueError("unsupported public mesh status version")
    generated_at = _parse_utc(snapshot["generated_at"], "status generated_at")
    monitor = snapshot["monitor"]
    _exact_keys(monitor, {"name", "method", "path", "schedule_minutes", "timeout_ms", "runner_region"}, "status monitor")
    if monitor["name"] != "OnceMesh directory monitor" or monitor["method"] != "unauthenticated-https" or monitor["path"] != STATUS_PATH:
        raise ValueError("status monitor methodology is unsupported")
    if isinstance(monitor["schedule_minutes"], bool) or not isinstance(monitor["schedule_minutes"], int) or not 5 <= monitor["schedule_minutes"] <= 1440:
        raise ValueError("status monitor schedule is invalid")
    if isinstance(monitor["timeout_ms"], bool) or not isinstance(monitor["timeout_ms"], int) or not 100 <= monitor["timeout_ms"] <= 30000:
        raise ValueError("status monitor timeout is invalid")
    if not isinstance(monitor["runner_region"], str) or not monitor["runner_region"] or len(monitor["runner_region"]) > 80:
        raise ValueError("status monitor runner region is invalid")
    observations = snapshot["meshes"]
    if not isinstance(observations, list) or len(observations) != len(meshes):
        raise ValueError("status observations must match the directory")
    for mesh, observation in zip(meshes, observations, strict=True):
        _exact_keys(observation, {"peer_id", "registry_status", "state", "checked_at", "response_time_ms", "http_status", "detail"}, "status observation")
        if observation["peer_id"] != mesh["peer_id"] or observation["registry_status"] != mesh["status"]:
            raise ValueError("status observation does not match its directory entry")
        state = observation["state"]
        if state not in STATUS_STATES or observation["registry_status"] not in MESH_STATUSES:
            raise ValueError("status observation state is invalid")
        checked = observation["checked_at"]
        response_time = observation["response_time_ms"]
        http_status = observation["http_status"]
        detail = observation["detail"]
        if state == "not_checked":
            if mesh["status"] in ACTIVE_REGISTRY_STATUSES or any(value is not None for value in (checked, response_time, http_status)) or detail != "registry-inactive":
                raise ValueError("inactive status observation is inconsistent")
            continue
        if mesh["status"] not in ACTIVE_REGISTRY_STATUSES or checked is None:
            raise ValueError("active status observation is inconsistent")
        if _parse_utc(checked, "status checked_at") > generated_at:
            raise ValueError("status observation is newer than its snapshot")
        if state == "down":
            if response_time is not None or http_status is not None or detail != "network-failure":
                raise ValueError("down status observation is inconsistent")
            continue
        if isinstance(response_time, bool) or not isinstance(response_time, int) or not 0 <= response_time <= 30000:
            raise ValueError("status response time is invalid")
        if isinstance(http_status, bool) or not isinstance(http_status, int) or not 100 <= http_status <= 599:
            raise ValueError("status HTTP response is invalid")
        expected = http_status in EXPECTED_HTTP_STATUSES
        if (state, detail) != (("up", "expected-protocol-response") if expected else ("degraded", "unexpected-http-response")):
            raise ValueError("HTTP status observation is inconsistent")


def write_public_mesh_status(snapshot: dict[str, Any], path: str | Path) -> None:
    selected = Path(path)
    selected.parent.mkdir(parents=True, exist_ok=True)
    selected.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
