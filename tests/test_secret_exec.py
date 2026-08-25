from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncemesh.secret_exec import main  # noqa: E402


class SecretExecTests(unittest.TestCase):
    def test_rejects_invalid_environment_name(self) -> None:
        with patch.object(sys, "argv", ["secret-exec", "bad-name", "secret", "command"]):
            with self.assertRaisesRegex(SystemExit, "usage"):
                main()

    def test_rejects_missing_and_empty_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"
            with patch.object(sys, "argv", ["secret-exec", "PILOT_SEED", str(missing), "command"]):
                with self.assertRaisesRegex(SystemExit, "cannot be read"):
                    main()
            empty = Path(directory) / "empty"
            empty.write_text("  \n", encoding="ascii")
            with patch.object(sys, "argv", ["secret-exec", "PILOT_SEED", str(empty), "command"]):
                with self.assertRaisesRegex(SystemExit, "empty"):
                    main()

    def test_sets_only_named_variable_and_executes_exact_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "secret"
            secret.write_text("test-seed\n", encoding="ascii")
            arguments = ["secret-exec", "PILOT_SEED", str(secret), "program", "--flag"]
            with (
                patch.object(sys, "argv", arguments),
                patch.dict(os.environ, {}, clear=True),
                patch.object(os, "execvp", side_effect=RuntimeError("exec intercepted")) as execute,
            ):
                with self.assertRaisesRegex(RuntimeError, "intercepted"):
                    main()
                self.assertEqual(os.environ, {"PILOT_SEED": "test-seed"})
                execute.assert_called_once_with("program", ["program", "--flag"])


if __name__ == "__main__":
    unittest.main()
