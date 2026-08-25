from __future__ import annotations

import json
from pathlib import Path
import re
import tomllib
from urllib.parse import unquote

import yaml


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".git",
    ".oncemesh-cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "dist",
}
EXCLUDED_NAMES = {".coverage", "coverage.xml"}
REQUIRED = (
    ".github/dependabot.yml",
    ".github/pull_request_template.md",
    ".github/workflows/ci.yml",
    ".github/workflows/codeql.yml",
    ".github/workflows/release.yml",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "GOVERNANCE.md",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "SUPPORT.md",
    "docs/readiness.md",
    "directory/README.md",
    "directory/public-meshes.json",
    "directory/public-mesh-status.json",
    "evaluation/results/README.md",
    "spec/public-mesh-directory-v0.md",
    "spec/public-mesh-status-v0.md",
    "site/index.html",
    "site/assets/app.js",
    "site/assets/mark.svg",
    "site/assets/styles.css",
    "scripts/build_pages.py",
    "scripts/check_public_meshes.py",
    ".github/workflows/pages.yml",
)
FORBIDDEN_NAMES = {".env", "id_rsa", "id_ed25519", "private.seed"}
PRIVATE_KEY_MARKERS = (
    b"-----BEGIN " + b"PRIVATE KEY-----",
    b"-----BEGIN RSA " + b"PRIVATE KEY-----",
    b"-----BEGIN EC " + b"PRIVATE KEY-----",
    b"-----BEGIN OPENSSH " + b"PRIVATE KEY-----",
)
MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def source_files() -> list[Path]:
    values = []
    for path in ROOT.rglob("*"):
        if (
            not path.is_file()
            or path.name in EXCLUDED_NAMES
            or any(part in EXCLUDED_PARTS for part in path.parts)
        ):
            continue
        if any(part.endswith(".egg-info") for part in path.parts):
            continue
        values.append(path)
    return values


def verify_json(files: list[Path]) -> int:
    count = 0
    for path in files:
        if path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))
            count += 1
        elif path.suffix == ".jsonl":
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.strip():
                    try:
                        json.loads(line)
                    except json.JSONDecodeError as error:
                        raise ValueError(f"invalid JSONL in {path.relative_to(ROOT)}:{line_number}") from error
            count += 1
    return count


def verify_yaml(files: list[Path]) -> int:
    selected = [path for path in files if path.suffix in {".yml", ".yaml"}]
    for path in selected:
        yaml.safe_load(path.read_text(encoding="utf-8"))
    return len(selected)


def verify_links(files: list[Path]) -> int:
    checked = 0
    for path in files:
        if path.suffix != ".md":
            continue
        for target in MARKDOWN_LINK.findall(path.read_text(encoding="utf-8")):
            target = target.strip().strip("<>").split("#", 1)[0]
            if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
                continue
            resolved = (path.parent / unquote(target)).resolve()
            if not resolved.exists():
                raise ValueError(f"broken local link in {path.relative_to(ROOT)}: {target}")
            checked += 1
    return checked


def verify_versions() -> str:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_version = project["project"]["version"]
    source = (ROOT / "src" / "oncemesh" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', source, re.MULTILINE)
    if match is None or match.group(1) != package_version:
        raise ValueError("pyproject and public source versions differ")
    return package_version


def main() -> int:
    for relative in REQUIRED:
        if not (ROOT / relative).exists():
            raise ValueError(f"required repository file is missing: {relative}")
    files = source_files()
    for path in files:
        if path.name in FORBIDDEN_NAMES or path.suffix.lower() == ".key":
            raise ValueError(f"forbidden secret path: {path.relative_to(ROOT)}")
        data = path.read_bytes()
        if any(marker in data for marker in PRIVATE_KEY_MARKERS):
            raise ValueError(f"private-key material found in {path.relative_to(ROOT)}")
    json_count = verify_json(files)
    yaml_count = verify_yaml(files)
    link_count = verify_links(files)
    version = verify_versions()
    release_report = json.loads(
        (ROOT / "evaluation/results/release-candidate-0.1.0-20260825.json").read_text(encoding="utf-8")
    )
    for relative in release_report["related_evidence"]:
        if not (ROOT / relative).exists():
            raise ValueError(f"release report references missing evidence: {relative}")
    print(
        json.dumps(
            {
                "files_scanned": len(files),
                "json_documents": json_count,
                "local_links": link_count,
                "passed": True,
                "version": version,
                "yaml_documents": yaml_count,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
