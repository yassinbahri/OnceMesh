"""Strict aggregate evidence reporter for real organization pilots."""

from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from typing import Any, Iterable

from .canonical import canonical_json, digest_bytes


DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
DECIMAL = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label} must contain exactly {sorted(keys)}")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer of at least {minimum}")
    return value


def _decimal(value: Any, label: str, *, maximum: Decimal | None = None) -> Decimal:
    try:
        if not isinstance(value, str) or not DECIMAL.fullmatch(value):
            raise ValueError
        selected = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{label} must be a non-negative decimal string") from error
    if selected < 0 or (maximum is not None and selected > maximum):
        raise ValueError(f"{label} is outside its permitted range")
    return selected


def _date(value: Any, label: str) -> date:
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} must be an ISO 8601 calendar date") from error


def validate_pilot_config(config: dict[str, Any]) -> None:
    _exact(
        config,
        {
            "spec_version",
            "pilot_id",
            "organization_id",
            "environment_kind",
            "window",
            "operations",
            "owners",
            "thresholds",
        },
        "pilot config",
    )
    if config["spec_version"] != "oncemesh.organization-pilot/v0":
        raise ValueError("unsupported organization pilot spec_version")
    _text(config["pilot_id"], "pilot_id")
    _text(config["organization_id"], "organization_id")
    if config["environment_kind"] not in ("real", "synthetic"):
        raise ValueError("environment_kind must be real or synthetic")
    window = _exact(
        config["window"], {"starts_on", "ends_on", "minimum_observed_days"}, "window"
    )
    starts_on = _date(window["starts_on"], "starts_on")
    ends_on = _date(window["ends_on"], "ends_on")
    minimum_days = _integer(window["minimum_observed_days"], "minimum_observed_days", minimum=1)
    if ends_on < starts_on or minimum_days > (ends_on - starts_on).days + 1:
        raise ValueError("pilot window cannot satisfy minimum_observed_days")
    operations = config["operations"]
    if not isinstance(operations, list) or not operations:
        raise ValueError("operations must be a non-empty array")
    checked_operations = [_text(item, "operation") for item in operations]
    if len(set(checked_operations)) != len(checked_operations):
        raise ValueError("operations must be unique")
    owners = _exact(config["owners"], {"workload", "security", "operations"}, "owners")
    owner_ids = [_text(owners[role], f"{role} owner") for role in sorted(owners)]
    if len(set(owner_ids)) != len(owner_ids):
        raise ValueError("owner role identifiers must be distinct")
    thresholds = _exact(
        config["thresholds"],
        {
            "minimum_evaluations",
            "maximum_mismatches",
            "maximum_error_rate",
            "minimum_candidate_hit_rate",
            "minimum_verified_time_saved_ms",
            "minimum_verified_cost_saved",
            "maximum_mean_lookup_ms",
            "minimum_kill_switch_drills",
        },
        "thresholds",
    )
    _integer(thresholds["minimum_evaluations"], "minimum_evaluations", minimum=1)
    _integer(thresholds["maximum_mismatches"], "maximum_mismatches")
    _decimal(thresholds["maximum_error_rate"], "maximum_error_rate", maximum=Decimal(1))
    _decimal(
        thresholds["minimum_candidate_hit_rate"],
        "minimum_candidate_hit_rate",
        maximum=Decimal(1),
    )
    _decimal(thresholds["minimum_verified_time_saved_ms"], "minimum_verified_time_saved_ms")
    _decimal(thresholds["minimum_verified_cost_saved"], "minimum_verified_cost_saved")
    _decimal(thresholds["maximum_mean_lookup_ms"], "maximum_mean_lookup_ms")
    _integer(thresholds["minimum_kill_switch_drills"], "minimum_kill_switch_drills")


def validate_daily_record(record: dict[str, Any]) -> None:
    _exact(
        record,
        {
            "spec_version",
            "pilot_id",
            "date",
            "operation",
            "evaluations",
            "candidate_hits",
            "compared_hits",
            "mismatches",
            "substitutions",
            "errors",
            "lookup_duration_ms",
            "verified_time_saved_ms",
            "verified_cost_saved",
            "reusable_bytes",
            "kill_switch_drills",
            "evidence_digest",
        },
        "daily record",
    )
    if record["spec_version"] != "oncemesh.organization-pilot-daily/v0":
        raise ValueError("unsupported daily record spec_version")
    _text(record["pilot_id"], "pilot_id")
    _date(record["date"], "date")
    _text(record["operation"], "operation")
    for field in (
        "evaluations",
        "candidate_hits",
        "compared_hits",
        "mismatches",
        "substitutions",
        "errors",
        "reusable_bytes",
        "kill_switch_drills",
    ):
        _integer(record[field], field)
    for field in ("lookup_duration_ms", "verified_time_saved_ms"):
        _decimal(record[field], field)
    _decimal(record["verified_cost_saved"], "verified_cost_saved")
    if not isinstance(record["evidence_digest"], str) or not DIGEST.fullmatch(
        record["evidence_digest"]
    ):
        raise ValueError("evidence_digest must be a SHA-256 digest")
    evaluations = record["evaluations"]
    for field in ("candidate_hits", "compared_hits", "mismatches", "substitutions", "errors"):
        if record[field] > evaluations:
            raise ValueError(f"{field} cannot exceed evaluations")
    if record["mismatches"] > record["compared_hits"]:
        raise ValueError("mismatches cannot exceed compared_hits")


def pilot_report(config: dict[str, Any], records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    validate_pilot_config(config)
    selected = list(records)
    for record in selected:
        validate_daily_record(record)
    if not selected:
        raise ValueError("at least one daily record is required")
    starts_on = _date(config["window"]["starts_on"], "starts_on")
    ends_on = _date(config["window"]["ends_on"], "ends_on")
    configured_operations = set(config["operations"])
    identities: set[tuple[str, str]] = set()
    for record in selected:
        identity = (record["date"], record["operation"])
        if identity in identities:
            raise ValueError("daily records contain a duplicate date and operation")
        identities.add(identity)
        if record["pilot_id"] != config["pilot_id"]:
            raise ValueError("daily record pilot_id does not match config")
        if record["operation"] not in configured_operations:
            raise ValueError("daily record contains an unconfigured operation")
        recorded_on = _date(record["date"], "date")
        if not starts_on <= recorded_on <= ends_on:
            raise ValueError("daily record falls outside the pilot window")

    totals: dict[str, int | float | str] = {
        "evaluations": sum(item["evaluations"] for item in selected),
        "candidate_hits": sum(item["candidate_hits"] for item in selected),
        "compared_hits": sum(item["compared_hits"] for item in selected),
        "mismatches": sum(item["mismatches"] for item in selected),
        "substitutions": sum(item["substitutions"] for item in selected),
        "errors": sum(item["errors"] for item in selected),
        "lookup_duration_ms": format(
            sum((_decimal(item["lookup_duration_ms"], "lookup_duration_ms") for item in selected), Decimal(0)),
            "f",
        ),
        "verified_time_saved_ms": format(
            sum(
                (
                    _decimal(item["verified_time_saved_ms"], "verified_time_saved_ms")
                    for item in selected
                ),
                Decimal(0),
            ),
            "f",
        ),
        "verified_cost_saved": str(
            sum((_decimal(item["verified_cost_saved"], "verified_cost_saved") for item in selected), Decimal(0))
        ),
        "reusable_bytes": sum(item["reusable_bytes"] for item in selected),
        "kill_switch_drills": sum(item["kill_switch_drills"] for item in selected),
    }
    evaluations = int(totals["evaluations"])
    hit_rate = Decimal(int(totals["candidate_hits"])) / evaluations if evaluations else Decimal(0)
    error_rate = Decimal(int(totals["errors"])) / evaluations if evaluations else Decimal(0)
    mean_lookup = Decimal(str(totals["lookup_duration_ms"])) / evaluations if evaluations else Decimal(0)
    observed_dates = sorted({item["date"] for item in selected})
    observed_operations = {item["operation"] for item in selected}
    thresholds = config["thresholds"]
    checks = {
        "real_environment": config["environment_kind"] == "real",
        "minimum_observed_days": len(observed_dates)
        >= config["window"]["minimum_observed_days"],
        "all_operations_observed": observed_operations == configured_operations,
        "minimum_evaluations": evaluations >= thresholds["minimum_evaluations"],
        "maximum_mismatches": int(totals["mismatches"])
        <= thresholds["maximum_mismatches"],
        "all_candidate_hits_compared": totals["candidate_hits"] == totals["compared_hits"],
        "maximum_error_rate": error_rate
        <= _decimal(thresholds["maximum_error_rate"], "maximum_error_rate"),
        "minimum_candidate_hit_rate": hit_rate
        >= _decimal(thresholds["minimum_candidate_hit_rate"], "minimum_candidate_hit_rate"),
        "minimum_verified_time_saved_ms": Decimal(str(totals["verified_time_saved_ms"]))
        >= _decimal(thresholds["minimum_verified_time_saved_ms"], "minimum_verified_time_saved_ms"),
        "minimum_verified_cost_saved": Decimal(str(totals["verified_cost_saved"]))
        >= _decimal(thresholds["minimum_verified_cost_saved"], "minimum_verified_cost_saved"),
        "maximum_mean_lookup_ms": mean_lookup
        <= _decimal(thresholds["maximum_mean_lookup_ms"], "maximum_mean_lookup_ms"),
        "minimum_kill_switch_drills": int(totals["kill_switch_drills"])
        >= thresholds["minimum_kill_switch_drills"],
    }
    evidence_digest = digest_bytes(
        canonical_json(
            {
                "config": config,
                "daily_evidence_digests": sorted(item["evidence_digest"] for item in selected),
            }
        )
    )
    return {
        "spec_version": "oncemesh.organization-pilot-report/v0",
        "pilot_id": config["pilot_id"],
        "organization_id": config["organization_id"],
        "environment_kind": config["environment_kind"],
        "observed_dates": observed_dates,
        "record_count": len(selected),
        "totals": totals,
        "rates": {
            "candidate_hit_rate": format(hit_rate, "f"),
            "error_rate": format(error_rate, "f"),
            "mean_lookup_ms": format(mean_lookup, "f"),
        },
        "checks": checks,
        "evidence_digest": evidence_digest,
        "externally_reviewable": all(checks.values()),
    }


def _load(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read JSON evidence: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"JSON evidence must be an object: {path}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="oncemesh-pilot")
    subparsers = parser.add_subparsers(dest="command", required=True)
    report_parser = subparsers.add_parser("report", help="generate a pilot report")
    report_parser.add_argument("--config", required=True)
    report_parser.add_argument("--record", action="append", required=True)
    report_parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    output = Path(args.output).resolve()
    if output.exists():
        raise ValueError("pilot report output already exists")
    report = pilot_report(_load(args.config), [_load(path) for path in args.record])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_json(report) + b"\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["externally_reviewable"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
