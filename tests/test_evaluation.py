from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncemesh import (  # noqa: E402
    EvaluationEvent,
    FilesystemStore,
    JsonlMetrics,
    publish_result,
    read_jsonl,
)
from oncemesh.adapters import (  # noqa: E402
    FetchResponse,
    SafeHTTPTransport,
    build_http_fetch_action,
    response_to_artifacts,
)
from oncemesh.evaluation import (  # noqa: E402
    promotion_report,
    run_evaluation,
    run_pdf_evaluation,
    run_pdf_substitution_evaluation,
    run_revalidation_evaluation,
    substitution_report,
    validate_evaluation_manifest,
)


def manifest() -> dict:
    return {
        "spec_version": "oncemesh.evaluation/v0",
        "name": "deterministic-test",
        "allowed_hosts": ["example.com"],
        "repetitions": 2,
        "request_delay_ms": 0,
        "urls": [
            {
                "url": "https://example.com/",
                "accept": "text/html",
                "freshness_seconds": 3600,
                "estimated_fetch_cost": "0.001000",
            }
        ],
        "promotion": {
            "minimum_candidate_hits": 2,
            "maximum_mismatches": 0,
            "minimum_candidate_match_rate": "1.000000",
        },
    }


class SafeTransportTests(unittest.TestCase):
    def test_public_allowlisted_target_is_accepted(self) -> None:
        transport = SafeHTTPTransport(["example.com"], resolver=lambda host, port: ["93.184.216.34"])
        self.assertEqual(transport.validate_target("https://EXAMPLE.com"), "https://example.com/")

    def test_private_address_is_rejected(self) -> None:
        transport = SafeHTTPTransport(["internal.test"], resolver=lambda host, port: ["127.0.0.1"])
        with self.assertRaisesRegex(ValueError, "non-global"):
            transport.validate_target("https://internal.test/")

    def test_non_allowlisted_host_is_rejected_before_resolution(self) -> None:
        transport = SafeHTTPTransport(["example.com"], resolver=lambda host, port: ["93.184.216.34"])
        with self.assertRaisesRegex(ValueError, "not allowlisted"):
            transport.validate_target("https://other.example/")


class EvaluationRunnerTests(unittest.TestCase):
    def test_pipeline_produces_passing_report_on_second_repetition(self) -> None:
        calls = 0

        def transport(url: str, accept: str, redirects: bool, limit: int) -> FetchResponse:
            nonlocal calls
            calls += 1
            return FetchResponse(
                status=200,
                final_url=url,
                headers={"Content-Type": "text/html; charset=utf-8", "ETag": "stable"},
                body=b"<h1>Example</h1><p>Stable page.</p>",
            )

        with tempfile.TemporaryDirectory() as directory:
            report = run_evaluation(
                manifest(),
                store_path=Path(directory) / "store",
                metrics_path=Path(directory) / "metrics.jsonl",
                evaluation_id="test-run",
                transport=transport,
            )
            self.assertEqual(calls, 2, "shadow mode must always execute the transport")
            self.assertEqual(report["summary"]["evaluations"], 4)
            self.assertEqual(report["summary"]["candidate_hits"], 2)
            self.assertEqual(report["summary"]["candidate_mismatches"], 0)
            self.assertTrue(report["promotion_review_ready"])

    def test_incomplete_evaluation_fails_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metrics.jsonl"
            JsonlMetrics(path).record(
                EvaluationEvent(
                    mode="shadow",
                    action_digest="sha256:" + "a" * 64,
                    operation="http.fetch",
                    candidate_hit=False,
                    tier=None,
                    artifact_match=None,
                    rejections=(),
                    execution_duration_ms=1.0,
                    reusable_bytes=0,
                    verified_time_saved_ms=0.0,
                    verified_cost_saved=0.0,
                    evaluation_id="partial",
                )
            )
            report = promotion_report(manifest(), path, "partial")
            self.assertFalse(report["checks"]["evaluation_complete"])
            self.assertFalse(report["promotion_review_ready"])

    def test_conditional_substitution_report_returns_schema_shaped_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metrics.jsonl"
            metrics = JsonlMetrics(path)
            for index in range(2):
                metrics.record(
                    EvaluationEvent(
                        mode="substitute",
                        action_digest="sha256:" + f"{index + 1:x}" * 64,
                        operation="http.fetch/1",
                        candidate_hit=True,
                        tier="organization",
                        artifact_match=None,
                        rejections=(),
                        execution_duration_ms=0,
                        reusable_bytes=100,
                        verified_time_saved_ms=0,
                        verified_cost_saved=0,
                        evaluation_id="conditional-substitution",
                        validation_method="http.conditional/1",
                        validation_status=304,
                        validation_recorded=True,
                        substituted=True,
                        decision_reason="conditional_304",
                    )
                )
            report = substitution_report(manifest(), path, "conditional-substitution")
            self.assertEqual(report["spec_version"], "oncemesh.substitution-report/v0")
            self.assertEqual(report["expected_evaluations"], 2)
            self.assertTrue(report["promotion_review_ready"])

    def test_pdf_pipeline_produces_passing_report_on_second_repetition(self) -> None:
        from test_pdf_adapter import fixture_pdf

        calls = 0
        pdf = fixture_pdf()

        def transport(url: str, accept: str, redirects: bool, limit: int) -> FetchResponse:
            nonlocal calls
            calls += 1
            return FetchResponse(200, url, {"Content-Type": "application/pdf"}, pdf)

        value = manifest()
        value["urls"][0]["accept"] = "application/pdf"
        with tempfile.TemporaryDirectory() as directory:
            report = run_pdf_evaluation(
                value,
                store_path=Path(directory) / "store",
                metrics_path=Path(directory) / "metrics.jsonl",
                evaluation_id="pdf-test-run",
                transport=transport,
            )
            self.assertEqual(calls, 2)
            self.assertEqual(report["summary"]["evaluations"], 4)
            self.assertEqual(report["summary"]["candidate_hits"], 2)
            self.assertEqual(report["summary"]["candidate_mismatches"], 0)
            self.assertTrue(report["promotion_review_ready"])

    def test_pdf_substitution_pipeline_uses_warmed_exact_result(self) -> None:
        from test_pdf_adapter import fixture_pdf
        from oncemesh.adapters import build_pdf_to_text_action, pdf_to_text_artifacts

        pdf = fixture_pdf()
        value = manifest()
        value["repetitions"] = 1
        value["urls"][0]["accept"] = "application/pdf"

        def transport(url: str, accept: str, redirects: bool, limit: int) -> FetchResponse:
            return FetchResponse(200, url, {"Content-Type": "application/pdf"}, pdf)

        with tempfile.TemporaryDirectory() as directory:
            store_path = Path(directory) / "store"
            store = FilesystemStore(store_path, name="evaluation-store")
            action = build_pdf_to_text_action(pdf)
            now = datetime.now(timezone.utc)
            publish_result(
                store,
                action,
                pdf_to_text_artifacts(action, pdf),
                producer="evaluation:local",
                produced_at=now,
                fresh_until=now + timedelta(hours=1),
            )
            policy_path = Path(directory) / "policy.json"
            policy_path.write_text(
                json.dumps(
                    {
                        "spec_version": "oncemesh.policy/v0",
                        "enabled": True,
                        "operations": {
                            "document.pdf-to-text/1": {
                                "mode": "exact-substitute",
                                "trusted_result_producers": ["evaluation:local"],
                                "trusted_validation_producers": [],
                                "allowed_tiers": ["evaluation-store"],
                                "max_validation_ttl_seconds": 3600,
                                "receipt_requirement": "optional",
                                "trusted_receipt_keys": [],
                                "authorization_partition": "public",
                                "max_stale_seconds": 0,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            report = run_pdf_substitution_evaluation(
                value,
                store_path=store_path,
                metrics_path=Path(directory) / "metrics.jsonl",
                policy_path=policy_path,
                evaluation_id="pdf-substitution-test",
                transport=transport,
            )
            self.assertTrue(report["promotion_review_ready"])
            self.assertEqual(report["summary"]["substitutions"], 1)

    def test_url_must_be_covered_by_allowlist(self) -> None:
        value = manifest()
        value["urls"][0]["url"] = "https://unreviewed.example/"
        with self.assertRaisesRegex(ValueError, "allowed_hosts"):
            validate_evaluation_manifest(value)

    def test_revalidation_runner_requires_and_records_preexisting_candidates(self) -> None:
        value = manifest()
        action = build_http_fetch_action("https://example.com/", accept="text/html")
        stable = FetchResponse(
            200,
            "https://example.com/",
            {"Content-Type": "text/html", "ETag": '"stable"'},
            b"<p>Stable</p>",
        )

        class Transport:
            def conditional_get(self, *args, **kwargs):
                return FetchResponse(
                    304,
                    "https://example.com/",
                    {"Content-Type": "text/html", "ETag": '"stable"'},
                    b"",
                )

            def __call__(self, *args, **kwargs):
                return stable

        with tempfile.TemporaryDirectory() as directory:
            store_path = Path(directory) / "store"
            store = FilesystemStore(store_path)
            now = datetime.now(timezone.utc)
            publish_result(
                store,
                action,
                response_to_artifacts(action, stable),
                producer="evaluation:local",
                produced_at=now - timedelta(hours=2),
                fresh_until=now - timedelta(hours=1),
            )
            report = run_revalidation_evaluation(
                value,
                store_path=store_path,
                metrics_path=Path(directory) / "revalidation.jsonl",
                evaluation_id="revalidation-test",
                transport=Transport(),
            )
            self.assertTrue(report["promotion_review_ready"])
            self.assertEqual(report["summary"]["conditional_not_modified"], 2)
            self.assertEqual(report["summary"]["validations_recorded"], 2)


class JsonlMetricsTests(unittest.TestCase):
    def test_truncated_final_line_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text('{"incomplete":', encoding="utf-8")
            self.assertEqual(read_jsonl(path), [])


if __name__ == "__main__":
    unittest.main()
