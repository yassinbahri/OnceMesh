"""Minimal Docker-secret-to-environment launcher for the simulated pilot."""

from __future__ import annotations

import os
from pathlib import Path
import re
import sys


def main() -> None:
    if len(sys.argv) < 4 or not re.fullmatch(r"[A-Z][A-Z0-9_]*", sys.argv[1]):
        raise SystemExit("usage: secret-exec ENV_NAME SECRET_FILE COMMAND [ARG ...]")
    environment_name = sys.argv[1]
    secret_file = Path(sys.argv[2])
    try:
        value = secret_file.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as error:
        raise SystemExit("configured secret cannot be read") from error
    if not value:
        raise SystemExit("configured secret is empty")
    os.environ[environment_name] = value
    os.execvp(sys.argv[3], sys.argv[3:])


if __name__ == "__main__":
    main()
