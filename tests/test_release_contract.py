from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import oncemesh  # noqa: E402


class ReleaseContractTests(unittest.TestCase):
    def test_package_and_runtime_versions_match_release_candidate(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(project["project"]["version"], "0.1.0")
        self.assertEqual(oncemesh.__version__, "0.1.0")
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "verify_release_tag.py"), "v0.1.0"],
            check=True,
            capture_output=True,
        )

    def test_release_files_and_json_schemas_are_present_and_parseable(self) -> None:
        for name in ("LICENSE", "CHANGELOG.md", "SECURITY.md", "docs/release.md"):
            self.assertTrue((ROOT / name).is_file(), name)
        schema_names = (
            "organization-pilot-v0.schema.json",
            "organization-pilot-daily-v0.schema.json",
            "organization-pilot-report-v0.schema.json",
        )
        for name in schema_names:
            value = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
            self.assertEqual(value["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_public_exports_are_unique_and_version_is_public(self) -> None:
        self.assertEqual(len(oncemesh.__all__), len(set(oncemesh.__all__)))
        self.assertIn("__version__", oncemesh.__all__)
        self.assertTrue(all(hasattr(oncemesh, name) for name in oncemesh.__all__))


if __name__ == "__main__":
    unittest.main()
