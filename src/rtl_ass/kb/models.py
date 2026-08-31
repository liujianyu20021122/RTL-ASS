"""Central knowledge-record invariants and lifecycle policy."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable, Mapping

from rtl_ass.errors import RtlAssError
from rtl_ass.integrity import canonical_json, hash_bytes, hash_json
from rtl_ass.kb.gates import validate_verification_gate


class RecordStatus(StrEnum):
    RAW = "raw"
    ANALYZED = "analyzed"
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    PROMOTED = "promoted"
    DEPRECATED = "deprecated"


class RecordRole(StrEnum):
    RTL_DESIGN = "rtl-design"
    TESTBENCH = "testbench"
    ASSERTION = "assertion"
    REFERENCE_MODEL = "reference-model"
    FIXTURE = "fixture"
    PACKAGE = "package"
    INTERFACE = "interface"
    DESIGN_PATTERN = "design-pattern"
    VERIFICATION_PATTERN = "verification-pattern"
    BUG_FIX = "bug-fix"
    TOOL_EVIDENCE = "tool-evidence"


class LicenseStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    INCOMPATIBLE = "incompatible"
    NOT_APPLICABLE = "not-applicable"


class ObservationAttribution(StrEnum):
    TARGET = "target"
    TESTBENCH = "testbench"
    SPECIFICATION = "specification"
    CONSTRAINTS = "constraints"
    INFRASTRUCTURE = "infrastructure"
    UNATTRIBUTED = "unattributed"


class LinkRelation(StrEnum):
    VERIFIES_DUT = "verifies-dut"
    ASSERTION_FOR = "assertion-for"
    REFERENCE_FOR = "reference-for"
    FIXTURE_FOR = "fixture-for"
    DERIVED_FROM = "derived-from"
    NEGATIVE_FOR = "negative-for"
    EVIDENCE_FOR = "evidence-for"


ALLOWED_TRANSITIONS: Mapping[RecordStatus, frozenset[RecordStatus]] = {
    RecordStatus.RAW: frozenset({RecordStatus.ANALYZED, RecordStatus.DEPRECATED}),
    RecordStatus.ANALYZED: frozenset({RecordStatus.CANDIDATE, RecordStatus.DEPRECATED}),
    RecordStatus.CANDIDATE: frozenset({RecordStatus.VERIFIED, RecordStatus.DEPRECATED}),
    RecordStatus.VERIFIED: frozenset({RecordStatus.PROMOTED, RecordStatus.DEPRECATED}),
    RecordStatus.PROMOTED: frozenset({RecordStatus.DEPRECATED}),
    RecordStatus.DEPRECATED: frozenset(),
}

LINK_ROLE_POLICY: Mapping[LinkRelation, tuple[frozenset[RecordRole], frozenset[RecordRole]]] = {
    LinkRelation.VERIFIES_DUT: (
        frozenset({RecordRole.TESTBENCH, RecordRole.VERIFICATION_PATTERN}),
        frozenset({RecordRole.RTL_DESIGN, RecordRole.DESIGN_PATTERN}),
    ),
    LinkRelation.ASSERTION_FOR: (
        frozenset({RecordRole.ASSERTION}),
        frozenset({RecordRole.RTL_DESIGN, RecordRole.DESIGN_PATTERN}),
    ),
    LinkRelation.REFERENCE_FOR: (
        frozenset({RecordRole.REFERENCE_MODEL}),
        frozenset({RecordRole.RTL_DESIGN, RecordRole.DESIGN_PATTERN}),
    ),
    LinkRelation.FIXTURE_FOR: (
        frozenset({RecordRole.FIXTURE}),
        frozenset({RecordRole.TESTBENCH, RecordRole.ASSERTION, RecordRole.RTL_DESIGN}),
    ),
    LinkRelation.DERIVED_FROM: (frozenset(RecordRole), frozenset(RecordRole)),
    LinkRelation.NEGATIVE_FOR: (
        frozenset({RecordRole.BUG_FIX, RecordRole.TOOL_EVIDENCE}),
        frozenset(RecordRole),
    ),
    LinkRelation.EVIDENCE_FOR: (
        frozenset({RecordRole.TOOL_EVIDENCE}),
        frozenset(RecordRole) - frozenset({RecordRole.TOOL_EVIDENCE}),
    ),
}

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


def validate_identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise RtlAssError(
            "invalid_identifier",
            f"{field_name} must start with an alphanumeric character and contain only safe identifier characters",
            {"field": field_name, "value": value},
        )
    return value


@dataclass(frozen=True, slots=True)
class KnowledgeRecordInput:
    namespace: str
    role: RecordRole
    language: str
    title: str
    summary: str
    content: str
    source_uri: str = ""
    source_revision: str = ""
    source_path: str = ""
    license_spdx: str = "UNKNOWN"
    license_status: LicenseStatus = LicenseStatus.UNKNOWN
    status: RecordStatus = RecordStatus.RAW
    metadata: Mapping[str, Any] = field(default_factory=dict)
    verification: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        validate_identifier(self.namespace, "namespace")
        if not isinstance(self.role, RecordRole):
            raise RtlAssError("invalid_record_role", "knowledge record role must use a supported value")
        if not isinstance(self.status, RecordStatus):
            raise RtlAssError("invalid_record_status", "knowledge record status must use a supported value")
        if not isinstance(self.license_status, LicenseStatus):
            raise RtlAssError("invalid_license_status", "knowledge record license status must use a supported value")
        if not isinstance(self.language, str) or not self.language or len(self.language) > 64:
            raise RtlAssError("invalid_language", "language must be between 1 and 64 characters")
        if not isinstance(self.title, str) or not self.title.strip() or len(self.title) > 512:
            raise RtlAssError("invalid_title", "title must be between 1 and 512 characters")
        if not isinstance(self.summary, str) or len(self.summary) > 4096:
            raise RtlAssError("invalid_summary", "summary must not exceed 4096 characters")
        if not isinstance(self.content, str) or not self.content:
            raise RtlAssError("empty_content", "knowledge content must be non-empty text")
        if self.status not in {RecordStatus.RAW, RecordStatus.CANDIDATE}:
            raise RtlAssError(
                "invalid_initial_status",
                "new records may only start as raw or candidate",
                {"status": self.status.value},
            )
        try:
            canonical_json(self.metadata)
            canonical_json(self.verification)
        except (TypeError, ValueError) as exc:
            raise RtlAssError(
                "invalid_record_json", "record metadata and verification must be finite JSON values"
            ) from exc

    @property
    def content_hash(self) -> str:
        return hash_bytes(self.content.encode("utf-8"))

    @property
    def identity(self) -> str:
        value = {
            "namespace": self.namespace,
            "role": self.role.value,
            "content_hash": self.content_hash,
            "source_uri": self.source_uri,
            "source_revision": self.source_revision,
            "source_path": self.source_path,
        }
        return hash_json(value)[:32]


def validate_transition(
    current: RecordStatus,
    target: RecordStatus,
    *,
    evidence: Mapping[str, Any] | None,
    content_hash: str,
    license_status: LicenseStatus,
    license_spdx: str,
    required_evidence_kinds: Iterable[str] = (),
) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise RtlAssError(
            "invalid_transition",
            f"knowledge status cannot transition from {current.value} to {target.value}",
            {"current": current.value, "target": target.value},
        )
    if target is RecordStatus.VERIFIED:
        validate_verification_gate(evidence, content_hash, required_evidence_kinds)
    if target is RecordStatus.PROMOTED:
        if license_status not in {LicenseStatus.KNOWN, LicenseStatus.NOT_APPLICABLE}:
            raise RtlAssError(
                "promotion_license_blocked",
                "promotion requires a known compatible license or a not-applicable license scope",
                {"license_status": license_status.value},
            )
        if license_status is LicenseStatus.KNOWN and license_spdx.upper() == "UNKNOWN":
            raise RtlAssError("promotion_license_missing", "known license status requires an SPDX identifier")


def validate_link_roles(relation: LinkRelation, source_role: RecordRole, target_role: RecordRole) -> None:
    allowed_source, allowed_target = LINK_ROLE_POLICY[relation]
    if source_role not in allowed_source or target_role not in allowed_target:
        raise RtlAssError(
            "invalid_link_roles",
            "record roles are incompatible with the requested relation",
            {
                "relation": relation.value,
                "source_role": source_role.value,
                "target_role": target_role.value,
            },
        )
