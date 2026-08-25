from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncemesh.discovery import load_public_mesh_directory  # noqa: E402
from oncemesh.mesh_status import generate_public_mesh_status, write_public_mesh_status  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a bounded public mesh reachability snapshot")
    parser.add_argument("--directory", type=Path, default=ROOT / "directory" / "public-meshes.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--schedule-minutes", type=int, default=30)
    parser.add_argument("--runner-region", default="github-hosted")
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()
    directory = load_public_mesh_directory(args.directory)
    snapshot = generate_public_mesh_status(
        directory,
        timeout_seconds=args.timeout_seconds,
        schedule_minutes=args.schedule_minutes,
        runner_region=args.runner_region,
        concurrency=args.concurrency,
    )
    write_public_mesh_status(snapshot, args.output)
    print(json.dumps({"checked": len(snapshot["meshes"]), "output": str(args.output), "passed": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
