"""Join declared knowledge use to receipt identities and independent behavioral checks.

This evaluates observable support, not the model's internal reasoning or causality.
The declaration is untrusted agent output; constraint checks come only from the host grader.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from rtl_ass.errors import RtlAssError
from rtl_ass.integrity import hash_file


def validate_usage(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"schema_version", "uses"} or value["schema_version"] != "1.0":
        raise RtlAssError("invalid_knowledge_usage", "usage root must contain schema_version 1.0 and uses")
    uses = value["uses"]
    if not isinstance(uses, list) or len(uses) > 3:
        raise RtlAssError("invalid_knowledge_usage", "uses must contain at most three records")
    seen: set[str] = set()
    for use in uses:
        fields = {"record_id", "content_hash", "decision", "reason", "target", "target_hash", "constraints"}
        if not isinstance(use, dict) or set(use) != fields:
            raise RtlAssError("invalid_knowledge_usage", "use fields do not match the contract")
        for key in ("record_id", "content_hash", "decision", "reason"):
            if not isinstance(use[key], str) or not use[key].strip() or len(use[key]) > 1024:
                raise RtlAssError("invalid_knowledge_usage", f"invalid {key}")
        if use["record_id"] in seen or not _digest(use["content_hash"]):
            raise RtlAssError("invalid_knowledge_usage", "duplicate record or invalid source hash")
        seen.add(use["record_id"])
        constraints = use["constraints"]
        if (
            not isinstance(constraints, list)
            or len(constraints) > 12
            or any(not isinstance(item, str) or not item.strip() or len(item) > 128 for item in constraints)
            or len(constraints) != len(set(constraints))
        ):
            raise RtlAssError("invalid_knowledge_usage", "constraints must be unique bounded identifiers")
        if use["decision"] == "rejected":
            if use["target"] is not None or use["target_hash"] is not None or constraints:
                raise RtlAssError("invalid_knowledge_usage", "rejection cannot claim a target or applied constraints")
        elif use["decision"] == "applied":
            target = use["target"]
            if (
                not isinstance(target, str)
                or not target
                or "\\" in target
                or PurePosixPath(target).is_absolute()
                or any(part in {"", ".", ".."} for part in target.split("/"))
                or not _digest(use["target_hash"])
                or not constraints
            ):
                raise RtlAssError(
                    "invalid_knowledge_usage", "application requires a local target, hash and constraints"
                )
        else:
            raise RtlAssError("invalid_knowledge_usage", "decision must be applied or rejected")
    return dict(value)


def _digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def audit_application(
    workspace: Path,
    retrieval: Mapping[str, Any],
    grade: Mapping[str, Any],
    treatment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    path = workspace / "artifacts" / "knowledge-use.json"
    base: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "not_reported",
        "uses": [],
        "supported_application_count": 0,
        "declared_rejection_count": 0,
        "unreported_read_ids": sorted(retrieval.get("content_bound_read_ids", [])),
        "causal_benefit": "not_established",
    }
    if not path.exists() and not path.is_symlink():
        return base
    try:
        if not _local_regular(workspace, path):
            raise RtlAssError("invalid_knowledge_usage", "usage must be a workspace-local regular file")
        base["declaration_hash"] = hash_file(path)
        declaration = validate_usage(json.loads(path.read_text(encoding="utf-8")))
    except (RtlAssError, OSError, ValueError) as exc:
        return {**base, "status": "invalid", "reason": exc.code if isinstance(exc, RtlAssError) else "invalid_json"}

    identities = {item["id"]: item for item in retrieval.get("returned_records", [])}
    inspected = set(retrieval.get("content_bound_read_ids", []))
    checks = grade.get("application_constraints", {})
    observations = []
    for use in declaration["uses"]:
        failures: list[str] = []
        record = identities.get(use["record_id"])
        if record is None or record["content_hash"] != use["content_hash"]:
            failures.append("source-not-bound-to-valid-receipt")
        elif record["status"] not in {"verified", "promoted"}:
            failures.append("source-not-calibrated")
        if not retrieval.get("database_integrity", {}).get("unchanged", False):
            failures.append("database-identity-not-preserved")
        constraint_results = {}
        if use["decision"] == "applied":
            if use["record_id"] not in inspected:
                failures.append("source-content-not-observably-read")
            target = workspace / use["target"]
            current = hash_file(target) if _local_regular(workspace, target) else None
            if current != use["target_hash"]:
                failures.append("target-missing-or-stale")
            for identifier in use["constraints"]:
                if treatment is None or identifier not in treatment.get("decision_targets", []):
                    failures.append(f"constraint-outside-reviewed-applicability:{identifier}")
                check = checks.get(identifier)
                # The host grader owns these entries, never the agent's declaration.
                supported = (
                    isinstance(check, dict)
                    and check.get("status") == "pass"
                    and check.get("target") == use["target"]
                    and check.get("target_hash") == current
                    and bool(check.get("evidence_file_hash"))
                )
                constraint_results[identifier] = "pass" if supported else "unsupported"
                if not supported:
                    failures.append(f"constraint-not-supported:{identifier}")
        outcome = (
            "unsupported"
            if failures
            else ("supported_application" if use["decision"] == "applied" else "declared_rejection")
        )
        observations.append(
            {**use, "source": record, "outcome": outcome, "checks": constraint_results, "failures": failures}
        )
    return {
        **base,
        "status": "audited",
        "uses": observations,
        "unreported_read_ids": sorted(inspected - {use["record_id"] for use in declaration["uses"]}),
        "supported_application_count": sum(item["outcome"] == "supported_application" for item in observations),
        "declared_rejection_count": sum(item["outcome"] == "declared_rejection" for item in observations),
    }


def _local_regular(workspace: Path, path: Path) -> bool:
    return (
        path.is_file()
        and path.resolve().is_relative_to(workspace.resolve())
        and not any(parent.is_symlink() for parent in (path, *path.parents) if parent != workspace.parent)
    )
