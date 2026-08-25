from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncemesh import (  # noqa: E402
    PUBLIC_DIRECTORY_URL,
    fetch_public_mesh_directory,
    load_public_mesh_directory,
    parse_public_mesh_directory,
    search_public_meshes,
    validate_public_mesh_directory,
)
from oncemesh.adapters.http_fetch import FetchResponse  # noqa: E402
from oncemesh.discovery import main  # noqa: E402


def vector() -> dict:
    document = json.loads(
        (ROOT / "conformance" / "public-mesh-directory-v0.json").read_text(encoding="utf-8")
    )
    return document["valid_directory"]


class PublicMeshDirectoryTests(unittest.TestCase):
    def test_canonical_empty_directory_and_conformance_vector_validate(self) -> None:
        canonical = load_public_mesh_directory(ROOT / "directory" / "public-meshes.json")
        self.assertEqual(validate_public_mesh_directory(canonical), ())
        self.assertEqual(validate_public_mesh_directory(vector())[0]["peer_id"], "example-eu")

    def test_search_filters_exact_operation_region_and_status(self) -> None:
        document = vector()
        self.assertEqual(len(search_public_meshes(document, operation="document.pdf-to-text/1")), 1)
        self.assertEqual(len(search_public_meshes(document, region="EU-WEST")), 1)
        self.assertEqual(len(search_public_meshes(document, status="observed")), 1)
        self.assertEqual(search_public_meshes(document, operation="http.fetch/1"), ())
        with self.assertRaisesRegex(ValueError, "name/version"):
            search_public_meshes(document, operation="document.pdf-to-text")

    def test_semantic_boundaries_fail_closed(self) -> None:
        mutations = (
            ("endpoint", "http://mesh.example.com"),
            ("status", "trusted"),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                document = vector()
                document["meshes"][0][field] = value
                with self.assertRaises(ValueError):
                    validate_public_mesh_directory(document)

        document = vector()
        document["meshes"][0]["endpoint"] = "https://127.0.0.1"
        with self.assertRaisesRegex(ValueError, "public host"):
            validate_public_mesh_directory(document)

        document = vector()
        document["meshes"][0]["stats"]["availability_ratio"] = "0.980000"
        with self.assertRaisesRegex(ValueError, "availability_ratio"):
            validate_public_mesh_directory(document)

        document = vector()
        document["meshes"][0]["stats"]["latency_ms"]["p95"] = "10"
        with self.assertRaisesRegex(ValueError, "p95"):
            validate_public_mesh_directory(document)

        document = vector()
        document["meshes"][0]["stats"]["evidence_kind"] = "operator-reported"
        with self.assertRaisesRegex(ValueError, "directory-observed"):
            validate_public_mesh_directory(document)

        document = vector()
        document["meshes"][0]["stats"].update(
            sample_size=30,
            successful_requests=20,
            availability_ratio="0.666667",
        )
        self.assertEqual(validate_public_mesh_directory(document)[0]["peer_id"], "example-eu")

    def test_duplicate_and_ordering_boundaries_are_rejected(self) -> None:
        first = vector()["meshes"][0]
        second = deepcopy(first)
        second["peer_id"] = "alpha"
        second["availability_identity"]["peer_id"] = "alpha"
        second["receipt_identities"][0]["peer_id"] = "alpha"
        document = vector()
        document["meshes"].append(second)
        with self.assertRaisesRegex(ValueError, "sorted"):
            validate_public_mesh_directory(document)

        document["meshes"].sort(key=lambda item: item["peer_id"])
        with self.assertRaisesRegex(ValueError, "endpoints"):
            validate_public_mesh_directory(document)

    def test_parser_rejects_duplicate_keys_and_oversized_documents(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            parse_public_mesh_directory(b'{"spec_version":"a","spec_version":"b"}')
        with self.assertRaisesRegex(ValueError, "byte limit"):
            parse_public_mesh_directory(b" " * 1_000_001)

    def test_fetch_is_bound_to_canonical_url_and_validates_response(self) -> None:
        body = json.dumps(vector()).encode("utf-8")
        calls = []

        def transport(url, accept, follow_redirects, maximum):
            calls.append((url, accept, follow_redirects, maximum))
            return FetchResponse(200, url, {"Content-Type": "application/json"}, body)

        fetched = fetch_public_mesh_directory(transport)
        self.assertEqual(fetched["meshes"][0]["peer_id"], "example-eu")
        self.assertEqual(calls[0][0], PUBLIC_DIRECTORY_URL)
        self.assertFalse(calls[0][2])

        def redirected(url, accept, follow_redirects, maximum):
            return FetchResponse(200, "https://example.com/directory.json", {}, body)

        with self.assertRaisesRegex(ValueError, "request failed"):
            fetch_public_mesh_directory(redirected)

    def test_cli_validates_lists_filters_and_inspects_local_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "public-meshes.json"
            path.write_text(json.dumps(vector()), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["validate", "--directory", str(path)]), 0)
            self.assertEqual(json.loads(output.getvalue()), {"meshes": 1, "valid": True})

            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(["list", "--directory", str(path), "--region", "eu-central"]),
                    0,
                )
            self.assertIn("example-eu [observed]", output.getvalue())
            self.assertIn("availability 99.0000%", output.getvalue())
            self.assertIn("p95 80.0 ms", output.getvalue())

            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["inspect", "--directory", str(path), "example-eu"]), 0)
            self.assertEqual(json.loads(output.getvalue())["endpoint"], "https://mesh.example.com")

            error = io.StringIO()
            with redirect_stderr(error):
                self.assertEqual(main(["inspect", "--directory", str(path), "missing"]), 2)
            self.assertIn("was not found", error.getvalue())


if __name__ == "__main__":
    unittest.main()
