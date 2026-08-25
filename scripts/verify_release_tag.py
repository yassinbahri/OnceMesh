from __future__ import annotations

import re
from pathlib import Path
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if len(sys.argv) != 2 or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", sys.argv[1]):
        raise SystemExit("usage: verify_release_tag.py vX.Y.Z")
    expected = sys.argv[1][1:]
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_version = project["project"]["version"]
    source = (ROOT / "src" / "oncemesh" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', source, re.MULTILINE)
    source_version = match.group(1) if match else None
    if package_version != expected or source_version != expected:
        raise SystemExit(
            f"release version mismatch: tag={expected}, package={package_version}, source={source_version}"
        )
    print(expected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
