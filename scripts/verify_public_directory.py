from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncemesh.discovery import validate_public_mesh_directory  # noqa: E402
from oncemesh.mesh_status import validate_public_mesh_status  # noqa: E402


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _replace_pointer(document: dict, pointer: str, value: object) -> None:
    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer.lstrip("/").split("/")]
    selected: object = document
    for part in parts[:-1]:
        selected = selected[int(part)] if isinstance(selected, list) else selected[part]
    if isinstance(selected, list):
        selected[int(parts[-1])] = value
    else:
        selected[parts[-1]] = value


def main() -> int:
    schema = _load(ROOT / "schemas" / "public-mesh-directory-v0.schema.json")
    status_schema = _load(ROOT / "schemas" / "public-mesh-status-v0.schema.json")
    directory = _load(ROOT / "directory" / "public-meshes.json")
    status = _load(ROOT / "directory" / "public-mesh-status.json")
    conformance = _load(ROOT / "conformance" / "public-mesh-directory-v0.json")
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator.check_schema(status_schema)
    checker = jsonschema.FormatChecker()
    for value in (directory, conformance["valid_directory"]):
        jsonschema.validate(value, schema, format_checker=checker)
        validate_public_mesh_directory(value)
    jsonschema.validate(status, status_schema, format_checker=checker)
    validate_public_mesh_status(status, directory)
    rejected = 0
    for case in conformance["invalid_mutations"]:
        invalid = deepcopy(conformance["valid_directory"])
        _replace_pointer(invalid, case["pointer"], case["value"])
        try:
            validate_public_mesh_directory(invalid)
        except ValueError:
            rejected += 1
        else:
            raise ValueError(f"invalid directory case was accepted: {case['name']}")
    print(json.dumps({"meshes": len(directory["meshes"]), "passed": True, "rejected_vectors": rejected, "schemas": 2}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
