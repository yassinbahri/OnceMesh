from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncemesh.discovery import load_public_mesh_directory  # noqa: E402
from oncemesh.mesh_status import validate_public_mesh_status  # noqa: E402


REQUIRED_SITE_FILES = {
    "index.html",
    "assets/app.js",
    "assets/mark.svg",
    "assets/styles.css",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the static OnceMesh directory site")
    parser.add_argument("--source", type=Path, default=ROOT / "site")
    parser.add_argument("--directory", type=Path, default=ROOT / "directory" / "public-meshes.json")
    parser.add_argument("--status", type=Path, default=ROOT / "directory" / "public-mesh-status.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.resolve()
    output = args.output.resolve()
    if output == source or source in output.parents:
        raise ValueError("Pages output must be outside the source directory")
    if output.exists():
        raise ValueError("Pages output must not already exist")
    available = {
        path.relative_to(source).as_posix()
        for path in source.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    missing = REQUIRED_SITE_FILES - available
    if missing:
        raise ValueError(f"Pages source is missing required files: {sorted(missing)}")
    if any(path.is_symlink() for path in source.rglob("*")):
        raise ValueError("Pages source must not contain symbolic links")

    directory = load_public_mesh_directory(args.directory)
    status = json.loads(args.status.read_text(encoding="utf-8"))
    validate_public_mesh_status(status, directory)

    shutil.copytree(source, output)
    data = output / "data"
    data.mkdir()
    shutil.copy2(args.directory, data / "public-meshes.json")
    shutil.copy2(args.status, data / "public-mesh-status.json")
    (output / ".nojekyll").write_text("", encoding="utf-8")
    print(
        json.dumps(
            {
                "files": sum(path.is_file() for path in output.rglob("*")),
                "meshes": len(directory["meshes"]),
                "output": str(output),
                "passed": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
