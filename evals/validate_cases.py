#!/usr/bin/env python3
"""Validate the public, answer-free RTL-ASS evaluation manifest."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT_FIELDS = {"schema_version", "suite", "effectiveness_status", "cases"}
CASE_FIELDS = {
    "id",
    "class",
    "prompt",
    "required_evidence",
    "acceptance",
    "forbidden_shortcuts",
}
EVIDENCE_KINDS = {"lint", "simulation", "waveform", "formal", "equivalence", "synthesis", "sta"}


def validate_manifest(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != ROOT_FIELDS:
        raise ValueError("evaluation manifest root fields do not match the 1.0 contract")
    if value["schema_version"] != "1.0" or value["effectiveness_status"] != "not_evaluated":
        raise ValueError("the public 1.0 manifest must remain explicitly not_evaluated")
    if not isinstance(value["suite"], str) or not value["suite"]:
        raise ValueError("suite must be non-empty text")
    cases = value["cases"]
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a non-empty array")
    identifiers: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != CASE_FIELDS:
            raise ValueError("case fields do not match the 1.0 contract")
        identifier = case["id"]
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise ValueError("case IDs must be non-empty and unique")
        identifiers.add(identifier)
        for field in ("class", "prompt"):
            if not isinstance(case[field], str) or not case[field]:
                raise ValueError(f"{identifier}.{field} must be non-empty text")
        for field in ("required_evidence", "acceptance", "forbidden_shortcuts"):
            items = case[field]
            if not isinstance(items, list) or not items or any(not isinstance(item, str) or not item for item in items):
                raise ValueError(f"{identifier}.{field} must be a non-empty text array")
            if len(set(items)) != len(items):
                raise ValueError(f"{identifier}.{field} must not contain duplicates")
        if not set(case["required_evidence"]).issubset(EVIDENCE_KINDS):
            raise ValueError(f"{identifier}.required_evidence contains an unsupported class")
    return value


def main(arguments: list[str] | None = None) -> int:
    paths = arguments if arguments is not None else sys.argv[1:]
    if len(paths) != 1:
        raise SystemExit("usage: validate_cases.py <cases.json>")
    path = Path(paths[0])
    value = json.loads(path.read_text(encoding="utf-8"))
    validated = validate_manifest(value)
    print(json.dumps({"schema_version": "1.0", "case_count": len(validated["cases"]), "status": "valid"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
