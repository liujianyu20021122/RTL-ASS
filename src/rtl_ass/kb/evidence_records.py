"""Construction of immutable tool-evidence knowledge records."""

from __future__ import annotations

from typing import Any, Mapping

from rtl_ass.integrity import canonical_json
from rtl_ass.kb.models import KnowledgeRecordInput, LicenseStatus, RecordRole, RecordStatus


def build_tool_evidence_record(
    target: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> KnowledgeRecordInput:
    tool = evidence["tool"]
    status = evidence["status"]
    return KnowledgeRecordInput(
        namespace=target["namespace"],
        role=RecordRole.TOOL_EVIDENCE,
        language="json",
        title=f"{evidence['kind']} {status} evidence {evidence['input_hash'][:12]}",
        summary=f"{evidence['kind']} {status} via {tool['name']} {tool['version']}",
        content=canonical_json(evidence),
        source_revision=evidence["input_hash"],
        source_path=evidence["evidence_file"],
        license_spdx="NONE",
        license_status=LicenseStatus.NOT_APPLICABLE,
        status=RecordStatus.CANDIDATE,
        metadata={
            "kind": evidence["kind"],
            "tool": tool,
            "input_hash": evidence["input_hash"],
            "subject_hashes": evidence["subject_hashes"],
        },
        verification={"run_status": status},
    )
