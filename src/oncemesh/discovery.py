"""Curated, non-authoritative public mesh directory client."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
import ipaddress
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable
from urllib.parse import urlsplit

from .adapters.http_fetch import FetchResponse
from .adapters.safe_http import SafeHTTPTransport
from .federation_pilot import validate_federation_identity

PUBLIC_DIRECTORY_VERSION = "oncemesh.public-mesh-directory/v0"
PUBLIC_DIRECTORY_URL = (
    "https://raw.githubusercontent.com/yassinbahri/OnceMesh/"
    "main/directory/public-meshes.json"
)
MAX_DIRECTORY_BYTES = 1_000_000
PEER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
UTC_PATTERN = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)
DECIMAL_PATTERN = re.compile(r"^(0|[1-9][0-9]*)(\.[0-9]+)?$")
RATIO_PATTERN = re.compile(r"^(0\.[0-9]{6}|1\.000000)$")
MESH_STATUSES = frozenset({"listed", "observed", "suspended", "retired"})


def _exact_keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{label} must contain exactly {sorted(expected)}")


def _strict_json(raw: str) -> Any:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON value {value} is unsupported")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)


def _bounded_text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{label} must be a non-empty string of at most {maximum} characters")
    if any(ord(character) < 0x20 for character in value):
        raise ValueError(f"{label} must not contain control characters")
    return value


def _utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not UTC_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must be a canonical UTC timestamp")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} is not a valid timestamp") from error


def _https_url(value: Any, label: str, *, origin_only: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError(f"{label} must be a bounded HTTPS URL")
    parsed = urlsplit(value)
    try:
        parsed.port
    except ValueError as error:
        raise ValueError(f"{label} port is invalid") from error
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (origin_only and parsed.path not in {"", "/"})
    ):
        qualifier = " origin" if origin_only else " URL"
        raise ValueError(f"{label} must be an HTTPS{qualifier} without credentials, query, or fragment")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost":
        raise ValueError(f"{label} must identify a public host")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError(f"{label} must identify a public host")
    return value


def _unique_texts(value: Any, label: str, *, maximum_items: int, maximum_length: int) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or len(value) > maximum_items
        or any(not isinstance(item, str) or not item or len(item) > maximum_length for item in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError(f"{label} must be a bounded non-empty unique string array")
    return tuple(value)


def _decimal(value: Any, label: str, pattern: re.Pattern[str] = DECIMAL_PATTERN) -> Decimal:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"{label} must be a canonical non-negative decimal string")
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{label} is invalid") from error


def _validate_stats(value: Any, *, status: str) -> None:
    if value is None:
        if status == "observed":
            raise ValueError("observed meshes require directory-observed statistics")
        return
    _exact_keys(
        value,
        {
            "evidence_kind",
            "window_started_at",
            "window_ended_at",
            "observed_at",
            "sample_size",
            "successful_requests",
            "bytes_served",
            "availability_ratio",
            "latency_ms",
        },
        "mesh statistics",
    )
    if value["evidence_kind"] not in {"operator-reported", "directory-observed"}:
        raise ValueError("statistics evidence_kind is unsupported")
    if status == "observed" and value["evidence_kind"] != "directory-observed":
        raise ValueError("observed meshes require directory-observed statistics")
    started = _utc(value["window_started_at"], "statistics window_started_at")
    ended = _utc(value["window_ended_at"], "statistics window_ended_at")
    observed = _utc(value["observed_at"], "statistics observed_at")
    if ended <= started or observed < ended:
        raise ValueError("statistics timestamps are not ordered")
    for field in ("sample_size", "successful_requests", "bytes_served"):
        if isinstance(value[field], bool) or not isinstance(value[field], int) or value[field] < 0:
            raise ValueError(f"statistics {field} must be a non-negative integer")
    if value["sample_size"] < 20:
        raise ValueError("statistics sample_size must be at least 20")
    if value["successful_requests"] > value["sample_size"]:
        raise ValueError("successful_requests must not exceed sample_size")
    ratio = _decimal(value["availability_ratio"], "availability_ratio", RATIO_PATTERN)
    measured_ratio = (
        Decimal(value["successful_requests"]) / Decimal(value["sample_size"])
    ).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    if ratio != measured_ratio:
        raise ValueError("availability_ratio must equal successful_requests divided by sample_size")
    _exact_keys(value["latency_ms"], {"p50", "p95"}, "statistics latency_ms")
    p50 = _decimal(value["latency_ms"]["p50"], "latency p50")
    p95 = _decimal(value["latency_ms"]["p95"], "latency p95")
    if p95 < p50:
        raise ValueError("latency p95 must be greater than or equal to p50")


def _validate_mesh(value: Any) -> dict[str, Any]:
    _exact_keys(
        value,
        {
            "peer_id",
            "display_name",
            "description",
            "operator",
            "endpoint",
            "regions",
            "status",
            "protocols",
            "operations",
            "availability_identity",
            "receipt_identities",
            "stats",
            "submitted_at",
        },
        "mesh profile",
    )
    peer_id = value["peer_id"]
    if not isinstance(peer_id, str) or not PEER_ID_PATTERN.fullmatch(peer_id):
        raise ValueError("mesh peer_id is invalid")
    _bounded_text(value["display_name"], "mesh display_name", 120)
    _bounded_text(value["description"], "mesh description", 500)
    _exact_keys(value["operator"], {"name", "website"}, "mesh operator")
    _bounded_text(value["operator"]["name"], "operator name", 120)
    _https_url(value["operator"]["website"], "operator website")
    _https_url(value["endpoint"], "mesh endpoint", origin_only=True)
    _unique_texts(value["regions"], "mesh regions", maximum_items=32, maximum_length=80)
    status = value["status"]
    if status not in MESH_STATUSES:
        raise ValueError("mesh status is unsupported")
    _unique_texts(value["protocols"], "mesh protocols", maximum_items=32, maximum_length=200)
    operations = value["operations"]
    if not isinstance(operations, list) or not operations or len(operations) > 1000:
        raise ValueError("mesh operations must be a bounded non-empty array")
    operation_keys: list[tuple[str, str, str]] = []
    for operation in operations:
        _exact_keys(operation, {"name", "version", "output_schema"}, "mesh operation")
        operation_keys.append(
            (
                _bounded_text(operation["name"], "operation name", 200),
                _bounded_text(operation["version"], "operation version", 100),
                _bounded_text(operation["output_schema"], "operation output_schema", 300),
            )
        )
    if len(set(operation_keys)) != len(operation_keys):
        raise ValueError("mesh operations must be unique")
    availability = value["availability_identity"]
    validate_federation_identity(availability, purpose="availability")
    if availability["peer_id"] != peer_id:
        raise ValueError("availability identity peer_id does not match mesh peer_id")
    receipts = value["receipt_identities"]
    if not isinstance(receipts, list) or not receipts or len(receipts) > 100:
        raise ValueError("receipt_identities must be a bounded non-empty array")
    receipt_keys: set[str] = set()
    for identity in receipts:
        validate_federation_identity(identity, purpose="receipt")
        if identity["peer_id"] != peer_id:
            raise ValueError("receipt identity peer_id does not match mesh peer_id")
        if identity["key_id"] in receipt_keys:
            raise ValueError("receipt identity key IDs must be unique")
        receipt_keys.add(identity["key_id"])
    _validate_stats(value["stats"], status=status)
    _utc(value["submitted_at"], "mesh submitted_at")
    return deepcopy(value)


def validate_public_mesh_directory(document: Any) -> tuple[dict[str, Any], ...]:
    _exact_keys(document, {"spec_version", "generated_at", "directory", "meshes"}, "public directory")
    if document["spec_version"] != PUBLIC_DIRECTORY_VERSION:
        raise ValueError("unsupported public directory version")
    _utc(document["generated_at"], "directory generated_at")
    _exact_keys(document["directory"], {"name", "repository", "policy_url"}, "directory metadata")
    _bounded_text(document["directory"]["name"], "directory name", 120)
    _https_url(document["directory"]["repository"], "directory repository")
    _https_url(document["directory"]["policy_url"], "directory policy_url")
    meshes = document["meshes"]
    if not isinstance(meshes, list) or len(meshes) > 10_000:
        raise ValueError("directory meshes must be a bounded array")
    validated = tuple(_validate_mesh(mesh) for mesh in meshes)
    peer_ids = [mesh["peer_id"] for mesh in validated]
    if peer_ids != sorted(peer_ids):
        raise ValueError("directory meshes must be sorted by peer_id")
    if len(set(peer_ids)) != len(peer_ids):
        raise ValueError("directory peer IDs must be unique")
    endpoints = [mesh["endpoint"].rstrip("/").lower() for mesh in validated]
    if len(set(endpoints)) != len(endpoints):
        raise ValueError("directory endpoints must be unique")
    return validated


def parse_public_mesh_directory(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_DIRECTORY_BYTES:
        raise ValueError("public directory exceeds the byte limit")
    try:
        value = _strict_json(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("public directory is not valid UTF-8 JSON") from error
    validate_public_mesh_directory(value)
    return value


def load_public_mesh_directory(path: str | Path) -> dict[str, Any]:
    selected = Path(path)
    try:
        with selected.open("rb") as source:
            raw = source.read(MAX_DIRECTORY_BYTES + 1)
    except OSError as error:
        raise ValueError(f"cannot read public directory {selected}") from error
    return parse_public_mesh_directory(raw)


DirectoryTransport = Callable[[str, str, bool, int], FetchResponse]


def fetch_public_mesh_directory(transport: DirectoryTransport | None = None) -> dict[str, Any]:
    selected = transport or SafeHTTPTransport(
        {"raw.githubusercontent.com"}, timeout_seconds=10, max_redirects=0
    )
    response = selected(PUBLIC_DIRECTORY_URL, "application/json", False, MAX_DIRECTORY_BYTES)
    if response.status != 200 or response.final_url != PUBLIC_DIRECTORY_URL:
        raise ValueError("canonical public directory request failed")
    return parse_public_mesh_directory(response.body)


def search_public_meshes(
    document: dict[str, Any],
    *,
    operation: str | None = None,
    region: str | None = None,
    status: str | None = None,
) -> tuple[dict[str, Any], ...]:
    meshes = validate_public_mesh_directory(document)
    if operation is not None and ("/" not in operation or operation.startswith("/") or operation.endswith("/")):
        raise ValueError("operation filter must use name/version")
    if status is not None and status not in MESH_STATUSES:
        raise ValueError("status filter is unsupported")
    selected: list[dict[str, Any]] = []
    for mesh in meshes:
        operation_match = operation is None or any(
            f"{item['name']}/{item['version']}" == operation for item in mesh["operations"]
        )
        region_match = region is None or any(
            item.casefold() == region.casefold() for item in mesh["regions"]
        )
        status_match = status is None or mesh["status"] == status
        if operation_match and region_match and status_match:
            selected.append(mesh)
    return tuple(selected)


def _source(args: argparse.Namespace) -> dict[str, Any]:
    return load_public_mesh_directory(args.directory) if args.directory else fetch_public_mesh_directory()


def _add_source(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--directory",
        help="read a local reviewed directory instead of the canonical HTTPS snapshot",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover public OnceMesh federation operators")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate a directory snapshot")
    _add_source(validate)
    listing = commands.add_parser("list", help="list and filter public meshes")
    _add_source(listing)
    listing.add_argument("--operation", help="exact operation filter in name/version form")
    listing.add_argument("--region", help="case-insensitive exact region filter")
    listing.add_argument("--status", choices=sorted(MESH_STATUSES))
    listing.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    inspect = commands.add_parser("inspect", help="show one public mesh profile")
    _add_source(inspect)
    inspect.add_argument("peer_id")
    args = parser.parse_args(argv)
    try:
        document = _source(args)
        if args.command == "validate":
            print(json.dumps({"meshes": len(document["meshes"]), "valid": True}, sort_keys=True))
            return 0
        if args.command == "list":
            meshes = search_public_meshes(
                document,
                operation=args.operation,
                region=args.region,
                status=args.status,
            )
            if args.json:
                print(json.dumps(list(meshes), indent=2, sort_keys=True))
            elif not meshes:
                print("No public meshes match the selected filters.")
            else:
                for mesh in meshes:
                    operations = ", ".join(
                        f"{item['name']}/{item['version']}" for item in mesh["operations"]
                    )
                    stats = mesh["stats"]
                    stats_line = "stats: not reported"
                    if stats is not None:
                        availability = Decimal(stats["availability_ratio"]) * 100
                        stats_line = (
                            f"stats: {stats['evidence_kind']}; availability {availability:.4f}%; "
                            f"p95 {stats['latency_ms']['p95']} ms; n={stats['sample_size']}; "
                            f"window ended {stats['window_ended_at']}"
                        )
                    print(
                        f"{mesh['peer_id']} [{mesh['status']}] — {mesh['display_name']}\n"
                        f"  {mesh['endpoint']}\n"
                        f"  regions: {', '.join(mesh['regions'])}; operations: {operations}\n"
                        f"  {stats_line}"
                    )
            return 0
        matches = [mesh for mesh in document["meshes"] if mesh["peer_id"] == args.peer_id]
        if not matches:
            raise ValueError("public mesh peer_id was not found")
        print(json.dumps(matches[0], indent=2, sort_keys=True))
        return 0
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
