from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import venv
import zipfile


EXPECTED_VERSION = "0.1.0"
FORBIDDEN_PARTS = (
    "__pycache__",
    ".pyc",
    ".oncemesh-cache",
    "evaluation/results",
    "private.seed",
)
FORBIDDEN_BYTES = (
    b"-----BEGIN " + b"PRIVATE KEY-----",
    b"-----BEGIN OPENSSH " + b"PRIVATE KEY-----",
)


def _check_names(names: list[str], label: str) -> None:
    normalized = [name.replace("\\", "/") for name in names]
    for name in normalized:
        if any(part in name for part in FORBIDDEN_PARTS):
            raise ValueError(f"{label} contains forbidden path: {name}")


def _check_bytes(data: bytes, label: str) -> None:
    if any(needle in data for needle in FORBIDDEN_BYTES):
        raise ValueError(f"{label} contains private-key material")


def _python(venv_root: Path) -> Path:
    return venv_root / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist", type=Path)
    args = parser.parse_args()
    wheels = sorted(args.dist.glob("*.whl"))
    sdists = sorted(args.dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError("distribution directory must contain exactly one wheel and one sdist")
    wheel, sdist = wheels[0], sdists[0]

    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        _check_names(names, "wheel")
        if not any(name.endswith("oncemesh/py.typed") for name in names):
            raise ValueError("wheel is missing oncemesh/py.typed")
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name)
        if f"Version: {EXPECTED_VERSION}".encode() not in metadata:
            raise ValueError("wheel metadata version is incorrect")
        if b"License-Expression: Apache-2.0" not in metadata:
            raise ValueError("wheel metadata is missing the Apache-2.0 license expression")
        for name in names:
            _check_bytes(archive.read(name), f"wheel member {name}")

    with tarfile.open(sdist, "r:gz") as archive:
        names = archive.getnames()
        _check_names(names, "sdist")
        required_suffixes = (
            "/LICENSE",
            "/CHANGELOG.md",
            "/CODE_OF_CONDUCT.md",
            "/GOVERNANCE.md",
            "/SECURITY.md",
            "/SUPPORT.md",
            "/spec/action-v0.md",
            "/schemas/action-v0.schema.json",
            "/conformance/node/run.mjs",
            "/docs/release.md",
            "/docs/readiness.md",
            "/directory/public-meshes.json",
            "/directory/public-mesh-status.json",
            "/spec/public-mesh-directory-v0.md",
            "/spec/public-mesh-status-v0.md",
            "/spec/public-reference-operator-v0.md",
            "/deploy/public-operator/Dockerfile",
            "/deploy/public-operator/README.md",
            "/deploy/public-operator/compose.yaml",
            "/deploy/public-operator/origin.json.template",
            "/schemas/public-mesh-directory-v0.schema.json",
            "/schemas/public-mesh-status-v0.schema.json",
            "/conformance/public-mesh-directory-v0.json",
            "/evaluation/organization-pilot/pilot.json.template",
            "/scripts/verify_pilot_schemas.py",
            "/scripts/verify_public_directory.py",
            "/scripts/check_public_meshes.py",
        )
        for suffix in required_suffixes:
            if not any(name.endswith(suffix) for name in names):
                raise ValueError(f"sdist is missing required source artifact: {suffix}")
        for member in archive.getmembers():
            if member.isfile():
                source = archive.extractfile(member)
                if source is not None:
                    _check_bytes(source.read(), f"sdist member {member.name}")

    with tempfile.TemporaryDirectory(prefix="oncemesh-wheel-smoke-") as directory:
        environment = Path(directory) / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = _python(environment)
        clean_environment = os.environ.copy()
        clean_environment.pop("PYTHONPATH", None)
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--force-reinstall",
                str(wheel.resolve()),
            ],
            check=True,
            env=clean_environment,
        )
        smoke = subprocess.run(
            [
                str(python),
                "-c",
                (
                    "import json, oncemesh; "
                    "from oncemesh import SQLiteActiveKeyIndex; "
                    "print(json.dumps({'version': oncemesh.__version__, "
                    "'sqlite': SQLiteActiveKeyIndex.__name__}, sort_keys=True))"
                ),
            ],
            check=True,
            capture_output=True,
            env=clean_environment,
            text=True,
        )
        value = json.loads(smoke.stdout)
        if value != {"sqlite": "SQLiteActiveKeyIndex", "version": EXPECTED_VERSION}:
            raise ValueError(f"clean wheel smoke returned unexpected data: {value}")
        for command in ("oncemesh-eval", "oncemesh-federation", "oncemesh-pilot", "oncemesh-discover"):
            executable = environment / (f"Scripts/{command}.exe" if sys.platform == "win32" else f"bin/{command}")
            subprocess.run(
                [str(executable), "--help"],
                check=True,
                capture_output=True,
                env=clean_environment,
            )
    print(json.dumps({"passed": True, "version": EXPECTED_VERSION, "wheel": wheel.name, "sdist": sdist.name}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
