from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class NodeConformanceTests(unittest.TestCase):
    def test_independent_node_runner_passes_shared_vectors(self) -> None:
        completed = subprocess.run(
            ["node", str(ROOT / "conformance" / "node" / "run.mjs")],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        report = json.loads(completed.stdout)
        self.assertTrue(report["passed"])
        self.assertGreaterEqual(report["checks"], 29)


if __name__ == "__main__":
    unittest.main()
