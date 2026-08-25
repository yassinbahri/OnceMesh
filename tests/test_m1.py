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
    FilesystemStore,
    InMemoryMetrics,
    MemoryStore,
    Policy,
    action_digest,
    publish_result,
    reuse,
    run_shadow,
)
from oncemesh.adapters import (  # noqa: E402
    FetchResponse,
    build_html_to_markdown_action,
    build_http_fetch_action,
    execute_http_fetch,
    html_to_markdown_artifacts,
    normalize_https_url,
)


def action() -> dict:
    return build_html_to_markdown_action(b"<h1>Hello</h1><p>World</p>")


class FilesystemStoreTests(unittest.TestCase):
    def test_result_survives_store_reopen(self) -> None:
        now = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            first = FilesystemStore(directory)
            publish_result(
                first,
                action(),
                {"document": (b"# Hello\n\nWorld\n", "text/markdown")},
                producer="team-a",
                produced_at=now,
                fresh_until=now + timedelta(hours=1),
            )
            reopened = FilesystemStore(directory)
            outcome = reuse(action(), [reopened], Policy(now=now))
            self.assertTrue(outcome.hit)
            self.assertEqual(outcome.artifacts["document"], b"# Hello\n\nWorld\n")

    def test_digest_cannot_be_used_as_a_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = FilesystemStore(directory)
            with self.assertRaises(ValueError):
                store.get_blob("sha256:../../secret")

    def test_malformed_manifest_is_an_explainable_miss(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = FilesystemStore(directory, name="project")
            target = store.action_root / action_digest(action())
            # _action_path removes the algorithm prefix; build through that checked helper.
            target = store._action_path(action_digest(action()))
            target.mkdir(parents=True)
            (target / "broken.json").write_text("not-json", encoding="utf-8")
            outcome = reuse(action(), [store])
            self.assertFalse(outcome.hit)
            self.assertEqual(outcome.rejections, ("project:manifest_read_failed",))


class ShadowModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
        self.store = MemoryStore("organization")
        self.metrics = InMemoryMetrics()

    def test_shadow_always_returns_executed_artifact_and_warms_store(self) -> None:
        actual = {"document": (b"fresh", "text/plain")}
        first = run_shadow(
            action(),
            [self.store],
            lambda: actual,
            self.metrics,
            publish_to=self.store,
            producer="team-a",
            fresh_until=self.now + timedelta(hours=1),
            now=self.now,
        )
        second = run_shadow(
            action(), [self.store], lambda: actual, self.metrics, now=self.now
        )
        self.assertFalse(first.lookup.hit)
        self.assertTrue(second.lookup.hit)
        self.assertTrue(second.artifact_match)
        self.assertEqual(second.artifacts, actual)
        self.assertEqual(self.metrics.summary()["verified_matches"], 1)

    def test_mismatch_does_not_count_savings(self) -> None:
        publish_result(
            self.store,
            action(),
            {"document": (b"old", "text/plain")},
            producer="team-a",
            produced_at=self.now,
            fresh_until=self.now + timedelta(hours=1),
        )
        outcome = run_shadow(
            action(),
            [self.store],
            lambda: {"document": (b"new", "text/plain")},
            self.metrics,
            estimated_execution_cost=1.5,
            now=self.now,
        )
        self.assertFalse(outcome.artifact_match)
        summary = self.metrics.summary()
        self.assertEqual(summary["candidate_mismatches"], 1)
        self.assertEqual(summary["verified_cost_saved"], 0.0)
        self.assertEqual(summary["verified_time_saved_ms"], 0.0)


class AdapterTests(unittest.TestCase):
    def test_url_normalization_is_conservative(self) -> None:
        self.assertEqual(
            normalize_https_url("HTTPS://Example.COM:443/docs?q=a%20b#top"),
            "https://example.com/docs?q=a%20b",
        )
        with self.assertRaises(ValueError):
            normalize_https_url("http://example.com")

    def test_http_transport_is_injected_and_response_is_normalized(self) -> None:
        built = build_http_fetch_action("https://example.com", accept="text/html", max_bytes=100)

        def transport(url: str, accept: str, redirects: bool, limit: int) -> FetchResponse:
            self.assertEqual((url, accept, redirects, limit), ("https://example.com/", "text/html", True, 100))
            return FetchResponse(
                200,
                "https://example.com/",
                {"Content-Type": "text/html", "ETag": "abc"},
                b"<p>Hello</p>",
            )

        artifacts = execute_http_fetch(built, transport)
        self.assertEqual(artifacts["body"], (b"<p>Hello</p>", "text/html"))
        metadata = json.loads(artifacts["metadata"][0])
        self.assertEqual(metadata["etag"], "abc")

    def test_html_profile_is_deterministic_and_ignores_script(self) -> None:
        html = b"<h1>Hello</h1><p>Some <strong>bold</strong> <a href='https://e.test'>link</a>.</p><script>bad()</script>"
        artifacts = html_to_markdown_artifacts(html)
        self.assertEqual(
            artifacts["document"],
            (b"# Hello\n\nSome **bold** [link](https://e.test).\n", "text/markdown; charset=utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
