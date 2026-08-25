from __future__ import annotations

from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncemesh.organization_pilot import (  # noqa: E402
    main,
    pilot_report,
    validate_daily_record,
    validate_pilot_config,
)


def config() -> dict:
    return {
        "spec_version": "oncemesh.organization-pilot/v0",
        "pilot_id": "synthetic-pilot",
        "organization_id": "synthetic-org",
        "environment_kind": "synthetic",
        "window": {
            "starts_on": "2026-09-01",
            "ends_on": "2026-09-30",
            "minimum_observed_days": 2,
        },
        "operations": ["document.pdf-to-text/1"],
        "owners": {
            "workload": "role-workload",
            "security": "role-security",
            "operations": "role-operations",
        },
        "thresholds": {
            "minimum_evaluations": 100,
            "maximum_mismatches": 0,
            "maximum_error_rate": "0.01",
            "minimum_candidate_hit_rate": "0.20",
            "minimum_verified_time_saved_ms": "1000",
            "minimum_verified_cost_saved": "1.00",
            "maximum_mean_lookup_ms": "10",
            "minimum_kill_switch_drills": 1,
        },
    }


def record(day: int, *, digest_character: str) -> dict:
    return {
        "spec_version": "oncemesh.organization-pilot-daily/v0",
        "pilot_id": "synthetic-pilot",
        "date": f"2026-09-{day:02d}",
        "operation": "document.pdf-to-text/1",
        "evaluations": 60,
        "candidate_hits": 20,
        "compared_hits": 20,
        "mismatches": 0,
        "substitutions": 18,
        "errors": 0,
        "lookup_duration_ms": "120",
        "verified_time_saved_ms": "800",
        "verified_cost_saved": "0.75",
        "reusable_bytes": 1000,
        "kill_switch_drills": 1 if day == 2 else 0,
        "evidence_digest": f"sha256:{digest_character * 64}",
    }


class OrganizationPilotTests(unittest.TestCase):
    def test_synthetic_evidence_can_test_thresholds_but_never_promote(self) -> None:
        report = pilot_report(config(), [record(1, digest_character="a"), record(2, digest_character="b")])
        self.assertFalse(report["checks"]["real_environment"])
        self.assertTrue(all(value for key, value in report["checks"].items() if key != "real_environment"))
        self.assertFalse(report["externally_reviewable"])
        self.assertEqual(report["totals"]["evaluations"], 120)
        self.assertEqual(report["totals"]["verified_cost_saved"], "1.50")
        self.assertRegex(report["evidence_digest"], r"^sha256:[0-9a-f]{64}$")

    def test_threshold_failures_are_individually_visible(self) -> None:
        weak = record(1, digest_character="a")
        weak["candidate_hits"] = 1
        weak["compared_hits"] = 0
        weak["errors"] = 2
        weak["mismatches"] = 0
        weak["verified_time_saved_ms"] = "0"
        weak["verified_cost_saved"] = "0.00"
        report = pilot_report(config(), [weak])
        for name in (
            "minimum_observed_days",
            "minimum_evaluations",
            "all_candidate_hits_compared",
            "maximum_error_rate",
            "minimum_candidate_hit_rate",
            "minimum_verified_time_saved_ms",
            "minimum_verified_cost_saved",
            "minimum_kill_switch_drills",
        ):
            self.assertFalse(report["checks"][name], name)

    def test_invalid_or_cross_pilot_records_fail_closed(self) -> None:
        valid = record(1, digest_character="a")
        cases = []
        wrong_pilot = deepcopy(valid)
        wrong_pilot["pilot_id"] = "other"
        cases.append(wrong_pilot)
        wrong_operation = deepcopy(valid)
        wrong_operation["operation"] = "unconfigured"
        cases.append(wrong_operation)
        outside = deepcopy(valid)
        outside["date"] = "2026-10-01"
        cases.append(outside)
        malformed_digest = deepcopy(valid)
        malformed_digest["evidence_digest"] = "sha256:no"
        with self.assertRaisesRegex(ValueError, "evidence_digest"):
            validate_daily_record(malformed_digest)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                pilot_report(config(), [value])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            pilot_report(config(), [valid, deepcopy(valid)])

    def test_config_rejects_impossible_window_and_owner_reuse(self) -> None:
        impossible = config()
        impossible["window"]["minimum_observed_days"] = 31
        with self.assertRaisesRegex(ValueError, "cannot satisfy"):
            validate_pilot_config(impossible)
        reused = config()
        reused["owners"]["security"] = reused["owners"]["workload"]
        with self.assertRaisesRegex(ValueError, "distinct"):
            validate_pilot_config(reused)

    def test_cli_writes_once_and_returns_two_for_synthetic_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            record_path = root / "record.json"
            output = root / "report.json"
            config_path.write_text(json.dumps(config()), encoding="utf-8")
            record_path.write_text(json.dumps(record(1, digest_character="a")), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                result = main(
                    [
                        "report",
                        "--config",
                        str(config_path),
                        "--record",
                        str(record_path),
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(result, 2)
            self.assertFalse(json.loads(output.read_text(encoding="utf-8"))["externally_reviewable"])
            with self.assertRaisesRegex(ValueError, "already exists"):
                main(
                    [
                        "report",
                        "--config",
                        str(config_path),
                        "--record",
                        str(record_path),
                        "--output",
                        str(output),
                    ]
                )


if __name__ == "__main__":
    unittest.main()
