"""End-to-end M1 evaluation runner and promotion report."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from time import sleep
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from .adapters import (
    SafeHTTPTransport,
    build_html_to_markdown_action,
    build_http_fetch_action,
    build_pdf_to_text_action,
    execute_http_fetch,
    html_to_markdown_artifacts,
    normalize_https_url,
    pdf_to_text_artifacts,
)
from .metrics import JsonlMetrics, read_jsonl, summarize
from .shadow import run_shadow
from .conditional import run_conditional_http_shadow
from .store import FilesystemStore
from .policy import FilePolicyRegistry
from .key_registry import FileReceiptKeyRegistry
from .runtime import execute_deterministic_with_policy, execute_http_with_policy

DECIMAL_PATTERN = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")


def _exact_keys(value: Any, keys: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label} must contain exactly {sorted(keys)}")


def validate_evaluation_manifest(manifest: dict[str, Any]) -> None:
    _exact_keys(
        manifest,
        {"spec_version", "name", "allowed_hosts", "repetitions", "request_delay_ms", "urls", "promotion"},
        "evaluation manifest",
    )
    if manifest["spec_version"] != "oncemesh.evaluation/v0":
        raise ValueError("unsupported evaluation spec_version")
    if not isinstance(manifest["name"], str) or not manifest["name"]:
        raise ValueError("evaluation name must not be empty")
    repetitions = manifest["repetitions"]
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or not 1 <= repetitions <= 100:
        raise ValueError("repetitions must be an integer from 1 through 100")
    delay = manifest["request_delay_ms"]
    if isinstance(delay, bool) or not isinstance(delay, int) or not 0 <= delay <= 60_000:
        raise ValueError("request_delay_ms must be an integer from 0 through 60000")
    hosts = manifest["allowed_hosts"]
    if not isinstance(hosts, list) or not hosts or any(not isinstance(host, str) or not host for host in hosts):
        raise ValueError("allowed_hosts must be a non-empty string array")
    normalized_hosts = {host.encode("idna").decode("ascii").lower().rstrip(".") for host in hosts}
    if len(normalized_hosts) != len(hosts):
        raise ValueError("allowed_hosts must be unique after normalization")
    urls = manifest["urls"]
    if not isinstance(urls, list) or not 1 <= len(urls) <= 1000:
        raise ValueError("urls must contain from 1 through 1000 entries")
    for item in urls:
        _exact_keys(item, {"url", "accept", "freshness_seconds", "estimated_fetch_cost"}, "URL entry")
        normalized = normalize_https_url(item["url"])
        if (urlsplit(normalized).hostname or "").lower() not in normalized_hosts:
            raise ValueError("every URL host must appear in allowed_hosts")
        if not isinstance(item["accept"], str) or not item["accept"]:
            raise ValueError("accept must not be empty")
        freshness = item["freshness_seconds"]
        if isinstance(freshness, bool) or not isinstance(freshness, int) or freshness <= 0:
            raise ValueError("freshness_seconds must be positive")
        try:
            text_cost = item["estimated_fetch_cost"]
            if not isinstance(text_cost, str) or not DECIMAL_PATTERN.fullmatch(text_cost):
                raise ValueError
            cost = Decimal(text_cost)
        except (InvalidOperation, TypeError, ValueError) as error:
            raise ValueError("estimated_fetch_cost must be a non-negative decimal string") from error
        if cost < 0:
            raise ValueError("estimated_fetch_cost must be a non-negative decimal string")
    promotion = manifest["promotion"]
    _exact_keys(
        promotion,
        {"minimum_candidate_hits", "maximum_mismatches", "minimum_candidate_match_rate"},
        "promotion",
    )
    for field in ("minimum_candidate_hits", "maximum_mismatches"):
        if isinstance(promotion[field], bool) or not isinstance(promotion[field], int) or promotion[field] < 0:
            raise ValueError(f"{field} must be a non-negative integer")
    try:
        text_rate = promotion["minimum_candidate_match_rate"]
        if not isinstance(text_rate, str) or not DECIMAL_PATTERN.fullmatch(text_rate):
            raise ValueError
        match_rate = Decimal(text_rate)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError("minimum_candidate_match_rate must be a decimal string") from error
    if not Decimal(0) <= match_rate <= Decimal(1):
        raise ValueError("minimum_candidate_match_rate must be between zero and one")


def load_evaluation_manifest(path: str | Path) -> dict[str, Any]:
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_evaluation_manifest(manifest)
    return manifest


def promotion_report(manifest: dict[str, Any], metrics_path: str | Path, evaluation_id: str) -> dict[str, Any]:
    validate_evaluation_manifest(manifest)
    summary = summarize(read_jsonl(metrics_path, evaluation_id=evaluation_id))
    expected = manifest["repetitions"] * len(manifest["urls"]) * 2
    thresholds = manifest["promotion"]
    checks = {
        "evaluation_complete": summary["evaluations"] == expected,
        "minimum_candidate_hits": summary["candidate_hits"] >= thresholds["minimum_candidate_hits"],
        "maximum_mismatches": summary["candidate_mismatches"] <= thresholds["maximum_mismatches"],
        "minimum_candidate_match_rate": summary["candidate_match_rate"] >= float(thresholds["minimum_candidate_match_rate"]),
        "all_hits_compared": summary["candidate_hits"]
        == summary["verified_matches"] + summary["candidate_mismatches"],
    }
    return {
        "spec_version": "oncemesh.evaluation-report/v0",
        "evaluation_id": evaluation_id,
        "workload": manifest["name"],
        "expected_evaluations": expected,
        "summary": summary,
        "checks": checks,
        "promotion_review_ready": all(checks.values()),
    }


def revalidation_report(
    manifest: dict[str, Any], metrics_path: str | Path, evaluation_id: str
) -> dict[str, Any]:
    validate_evaluation_manifest(manifest)
    summary = summarize(read_jsonl(metrics_path, evaluation_id=evaluation_id))
    expected = manifest["repetitions"] * len(manifest["urls"])
    checks = {
        "evaluation_complete": summary["evaluations"] == expected,
        "all_candidates_found": summary["candidate_hits"] == expected,
        "all_candidates_compared": summary["verified_matches"] + summary["candidate_mismatches"]
        == summary["candidate_hits"],
        "zero_mismatches": summary["candidate_mismatches"] == 0,
        "conditional_validation_observed": summary["conditional_not_modified"] > 0,
        "every_304_recorded": summary["validations_recorded"]
        == summary["conditional_not_modified"],
    }
    return {
        "spec_version": "oncemesh.revalidation-report/v0",
        "evaluation_id": evaluation_id,
        "workload": manifest["name"],
        "expected_evaluations": expected,
        "summary": summary,
        "checks": checks,
        "promotion_review_ready": all(checks.values()),
    }


def substitution_report(
    manifest: dict[str, Any], metrics_path: str | Path, evaluation_id: str
) -> dict[str, Any]:
    validate_evaluation_manifest(manifest)
    summary = summarize(read_jsonl(metrics_path, evaluation_id=evaluation_id))
    expected = manifest["repetitions"] * len(manifest["urls"])
    checks = {
        "evaluation_complete": summary["evaluations"] == expected,
        "every_operation_substituted": summary["substitutions"] == expected,
        "every_source_not_modified": summary["conditional_not_modified"] == expected,
        "no_kill_switch_activation": summary["kill_switch_activations"] == 0,
        "only_conditional_304_decisions": summary["decision_reasons"]
        == {"conditional_304": expected},
    }
    return {
        "spec_version": "oncemesh.substitution-report/v0",
        "evaluation_id": evaluation_id,
        "workload": manifest["name"],
        "expected_evaluations": expected,
        "summary": summary,
        "checks": checks,
        "promotion_review_ready": all(checks.values()),
    }


def exact_substitution_report(
    manifest: dict[str, Any], metrics_path: str | Path, evaluation_id: str
) -> dict[str, Any]:
    validate_evaluation_manifest(manifest)
    summary = summarize(read_jsonl(metrics_path, evaluation_id=evaluation_id))
    expected = manifest["repetitions"] * len(manifest["urls"])
    checks = {
        "evaluation_complete": summary["evaluations"] == expected,
        "every_operation_substituted": summary["substitutions"] == expected,
        "no_kill_switch_activation": summary["kill_switch_activations"] == 0,
        "only_exact_fresh_hit_decisions": summary["decision_reasons"]
        == {"exact_fresh_hit": expected},
    }
    return {
        "spec_version": "oncemesh.exact-substitution-report/v0",
        "evaluation_id": evaluation_id,
        "workload": manifest["name"],
        "expected_evaluations": expected,
        "summary": summary,
        "checks": checks,
        "promotion_review_ready": all(checks.values()),
    }


def run_evaluation(
    manifest: dict[str, Any],
    *,
    store_path: str | Path,
    metrics_path: str | Path,
    evaluation_id: str | None = None,
    transport=None,
) -> dict[str, Any]:
    validate_evaluation_manifest(manifest)
    selected_id = evaluation_id or f"{manifest['name']}-{uuid4().hex[:12]}"
    store = FilesystemStore(store_path, name="evaluation-store")
    metrics = JsonlMetrics(metrics_path)
    selected_transport = transport or SafeHTTPTransport(manifest["allowed_hosts"])

    for _ in range(manifest["repetitions"]):
        for item in manifest["urls"]:
            if manifest["request_delay_ms"]:
                sleep(manifest["request_delay_ms"] / 1000)
            now = datetime.now(timezone.utc)
            fresh_until = now + timedelta(seconds=item["freshness_seconds"])
            fetch_action = build_http_fetch_action(item["url"], accept=item["accept"])
            fetched = run_shadow(
                fetch_action,
                [store],
                lambda action=fetch_action: execute_http_fetch(action, selected_transport),
                metrics,
                estimated_execution_cost=float(item["estimated_fetch_cost"]),
                publish_to=store,
                producer="evaluation:local",
                fresh_until=fresh_until,
                now=now,
                evaluation_id=selected_id,
            )
            body, media_type = fetched.artifacts["body"]
            if not media_type.lower().startswith("text/html"):
                raise ValueError(f"evaluation URL did not return HTML content: {media_type}")
            markdown_action = build_html_to_markdown_action(body, media_type=media_type)
            run_shadow(
                markdown_action,
                [store],
                lambda body=body: html_to_markdown_artifacts(body),
                metrics,
                publish_to=store,
                producer="evaluation:local",
                fresh_until=fresh_until,
                now=now,
                evaluation_id=selected_id,
            )
    return promotion_report(manifest, metrics_path, selected_id)


def run_pdf_evaluation(
    manifest: dict[str, Any],
    *,
    store_path: str | Path,
    metrics_path: str | Path,
    evaluation_id: str | None = None,
    transport=None,
) -> dict[str, Any]:
    """Run fetch plus deterministic PDF extraction in always-execute shadow mode."""
    validate_evaluation_manifest(manifest)
    selected_id = evaluation_id or f"{manifest['name']}-{uuid4().hex[:12]}"
    store = FilesystemStore(store_path, name="evaluation-store")
    metrics = JsonlMetrics(metrics_path)
    selected_transport = transport or SafeHTTPTransport(manifest["allowed_hosts"])

    for _ in range(manifest["repetitions"]):
        for item in manifest["urls"]:
            if manifest["request_delay_ms"]:
                sleep(manifest["request_delay_ms"] / 1000)
            now = datetime.now(timezone.utc)
            fresh_until = now + timedelta(seconds=item["freshness_seconds"])
            fetch_action = build_http_fetch_action(item["url"], accept=item["accept"])
            fetched = run_shadow(
                fetch_action,
                [store],
                lambda action=fetch_action: execute_http_fetch(action, selected_transport),
                metrics,
                estimated_execution_cost=float(item["estimated_fetch_cost"]),
                publish_to=store,
                producer="evaluation:local",
                fresh_until=fresh_until,
                now=now,
                evaluation_id=selected_id,
            )
            body, media_type = fetched.artifacts["body"]
            if media_type.lower().split(";", 1)[0].strip() != "application/pdf":
                raise ValueError(f"evaluation URL did not return PDF content: {media_type}")
            parse_action = build_pdf_to_text_action(body, media_type=media_type)
            run_shadow(
                parse_action,
                [store],
                lambda action=parse_action, body=body: pdf_to_text_artifacts(action, body),
                metrics,
                publish_to=store,
                producer="evaluation:local",
                fresh_until=fresh_until,
                now=now,
                evaluation_id=selected_id,
            )
    return promotion_report(manifest, metrics_path, selected_id)


def run_pdf_substitution_evaluation(
    manifest: dict[str, Any],
    *,
    store_path: str | Path,
    metrics_path: str | Path,
    policy_path: str | Path,
    key_registry_path: str | Path | None = None,
    evaluation_id: str | None = None,
    transport=None,
) -> dict[str, Any]:
    """Fetch exact input bytes, then exercise policy-controlled PDF parse reuse."""
    validate_evaluation_manifest(manifest)
    selected_id = evaluation_id or f"{manifest['name']}-exact-{uuid4().hex[:12]}"
    store = FilesystemStore(store_path, name="evaluation-store")
    metrics = JsonlMetrics(metrics_path)
    registry = FilePolicyRegistry(policy_path)
    key_registry = FileReceiptKeyRegistry(key_registry_path) if key_registry_path else None
    selected_transport = transport or SafeHTTPTransport(manifest["allowed_hosts"])

    for _ in range(manifest["repetitions"]):
        for item in manifest["urls"]:
            if manifest["request_delay_ms"]:
                sleep(manifest["request_delay_ms"] / 1000)
            now = datetime.now(timezone.utc)
            fetch_action = build_http_fetch_action(item["url"], accept=item["accept"])
            fetched = execute_http_fetch(fetch_action, selected_transport)
            body, media_type = fetched["body"]
            if media_type.lower().split(";", 1)[0].strip() != "application/pdf":
                raise ValueError(f"evaluation URL did not return PDF content: {media_type}")
            parse_action = build_pdf_to_text_action(body, media_type=media_type)
            execute_deterministic_with_policy(
                parse_action,
                [store],
                lambda action=parse_action, body=body: pdf_to_text_artifacts(action, body),
                metrics,
                registry,
                key_registry=key_registry,
                publish_to=store,
                producer="runtime:local",
                freshness_seconds=item["freshness_seconds"],
                now=now,
                evaluation_id=selected_id,
            )
    return exact_substitution_report(manifest, metrics_path, selected_id)


def run_revalidation_evaluation(
    manifest: dict[str, Any],
    *,
    store_path: str | Path,
    metrics_path: str | Path,
    evaluation_id: str | None = None,
    transport=None,
) -> dict[str, Any]:
    validate_evaluation_manifest(manifest)
    selected_id = evaluation_id or f"{manifest['name']}-revalidation-{uuid4().hex[:12]}"
    store = FilesystemStore(store_path, name="evaluation-store")
    metrics = JsonlMetrics(metrics_path)
    selected_transport = transport or SafeHTTPTransport(manifest["allowed_hosts"])
    for _ in range(manifest["repetitions"]):
        for item in manifest["urls"]:
            if manifest["request_delay_ms"]:
                sleep(manifest["request_delay_ms"] / 1000)
            now = datetime.now(timezone.utc)
            fresh_until = now + timedelta(seconds=item["freshness_seconds"])
            action = build_http_fetch_action(item["url"], accept=item["accept"])
            run_conditional_http_shadow(
                action,
                [store],
                selected_transport,
                metrics,
                estimated_execution_cost=float(item["estimated_fetch_cost"]),
                publish_to=store,
                producer="evaluation:local",
                fresh_until=fresh_until,
                now=now,
                evaluation_id=selected_id,
            )
    return revalidation_report(manifest, metrics_path, selected_id)


def run_substitution_evaluation(
    manifest: dict[str, Any],
    *,
    store_path: str | Path,
    metrics_path: str | Path,
    policy_path: str | Path,
    evaluation_id: str | None = None,
    transport=None,
) -> dict[str, Any]:
    validate_evaluation_manifest(manifest)
    selected_id = evaluation_id or f"{manifest['name']}-substitution-{uuid4().hex[:12]}"
    store = FilesystemStore(store_path, name="evaluation-store")
    metrics = JsonlMetrics(metrics_path)
    selected_transport = transport or SafeHTTPTransport(manifest["allowed_hosts"])
    registry = FilePolicyRegistry(policy_path)
    for _ in range(manifest["repetitions"]):
        for item in manifest["urls"]:
            if manifest["request_delay_ms"]:
                sleep(manifest["request_delay_ms"] / 1000)
            action = build_http_fetch_action(item["url"], accept=item["accept"])
            execute_http_with_policy(
                action,
                [store],
                selected_transport,
                metrics,
                registry,
                publish_to=store,
                producer="runtime:local",
                validation_ttl_seconds=item["freshness_seconds"],
                estimated_execution_cost=float(item["estimated_fetch_cost"]),
                now=datetime.now(timezone.utc),
                evaluation_id=selected_id,
            )
    return substitution_report(manifest, metrics_path, selected_id)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oncemesh-eval")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run a shadow evaluation workload")
    run.add_argument("--manifest", required=True)
    run.add_argument("--store", required=True)
    run.add_argument("--metrics", required=True)
    run.add_argument("--evaluation-id")
    pdf_run = commands.add_parser("pdf-run", help="run a PDF extraction shadow workload")
    pdf_run.add_argument("--manifest", required=True)
    pdf_run.add_argument("--store", required=True)
    pdf_run.add_argument("--metrics", required=True)
    pdf_run.add_argument("--evaluation-id")
    pdf_substitute = commands.add_parser(
        "pdf-substitute", help="run policy-controlled exact PDF parse substitution"
    )
    pdf_substitute.add_argument("--manifest", required=True)
    pdf_substitute.add_argument("--store", required=True)
    pdf_substitute.add_argument("--metrics", required=True)
    pdf_substitute.add_argument("--policy", required=True)
    pdf_substitute.add_argument("--key-registry")
    pdf_substitute.add_argument("--evaluation-id")
    report = commands.add_parser("report", help="report one evaluation ID")
    report.add_argument("--manifest", required=True)
    report.add_argument("--metrics", required=True)
    report.add_argument("--evaluation-id", required=True)
    revalidate = commands.add_parser("revalidate", help="run conditional HTTP shadow validation")
    revalidate.add_argument("--manifest", required=True)
    revalidate.add_argument("--store", required=True)
    revalidate.add_argument("--metrics", required=True)
    revalidate.add_argument("--evaluation-id")
    revalidation_report_parser = commands.add_parser(
        "revalidation-report", help="report one conditional validation evaluation"
    )
    revalidation_report_parser.add_argument("--manifest", required=True)
    revalidation_report_parser.add_argument("--metrics", required=True)
    revalidation_report_parser.add_argument("--evaluation-id", required=True)
    substitute = commands.add_parser("substitute", help="run policy-controlled HTTP substitution")
    substitute.add_argument("--manifest", required=True)
    substitute.add_argument("--store", required=True)
    substitute.add_argument("--metrics", required=True)
    substitute.add_argument("--policy", required=True)
    substitute.add_argument("--evaluation-id")
    substitution_report_parser = commands.add_parser(
        "substitution-report", help="report one policy substitution evaluation"
    )
    substitution_report_parser.add_argument("--manifest", required=True)
    substitution_report_parser.add_argument("--metrics", required=True)
    substitution_report_parser.add_argument("--evaluation-id", required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    manifest = load_evaluation_manifest(args.manifest)
    if args.command == "run":
        result = run_evaluation(
            manifest,
            store_path=args.store,
            metrics_path=args.metrics,
            evaluation_id=args.evaluation_id,
        )
    elif args.command == "pdf-run":
        result = run_pdf_evaluation(
            manifest,
            store_path=args.store,
            metrics_path=args.metrics,
            evaluation_id=args.evaluation_id,
        )
    elif args.command == "pdf-substitute":
        result = run_pdf_substitution_evaluation(
            manifest,
            store_path=args.store,
            metrics_path=args.metrics,
            policy_path=args.policy,
            key_registry_path=args.key_registry,
            evaluation_id=args.evaluation_id,
        )
    elif args.command == "report":
        result = promotion_report(manifest, args.metrics, args.evaluation_id)
    elif args.command == "revalidate":
        result = run_revalidation_evaluation(
            manifest,
            store_path=args.store,
            metrics_path=args.metrics,
            evaluation_id=args.evaluation_id,
        )
    elif args.command == "revalidation-report":
        result = revalidation_report(manifest, args.metrics, args.evaluation_id)
    elif args.command == "substitute":
        result = run_substitution_evaluation(
            manifest,
            store_path=args.store,
            metrics_path=args.metrics,
            policy_path=args.policy,
            evaluation_id=args.evaluation_id,
        )
    else:
        result = substitution_report(manifest, args.metrics, args.evaluation_id)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
