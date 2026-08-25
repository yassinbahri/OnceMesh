from __future__ import annotations

import json
from pathlib import Path
import sys

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from oncemesh.organization_pilot import (  # noqa: E402
    pilot_report,
    validate_daily_record,
    validate_pilot_config,
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    template_root = ROOT / "evaluation" / "organization-pilot"
    schema_root = ROOT / "schemas"
    config = _load(template_root / "pilot.json.template")
    daily = _load(template_root / "daily.json.template")
    daily["evidence_digest"] = "sha256:" + "a" * 64

    validate_pilot_config(config)
    validate_daily_record(daily)
    report = pilot_report(config, [daily])
    values = (
        ("organization-pilot-v0.schema.json", config),
        ("organization-pilot-daily-v0.schema.json", daily),
        ("organization-pilot-report-v0.schema.json", report),
    )
    for schema_name, value in values:
        schema = _load(schema_root / schema_name)
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(value, schema)
    print(json.dumps({"passed": True, "schemas": len(values)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
