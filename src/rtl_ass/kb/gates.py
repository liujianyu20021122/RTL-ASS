"""Central verification-gate and run-evidence validation."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from rtl_ass.errors import RtlAssError
from rtl_ass.integrity import canonical_json, hash_file, parse_json

EVIDENCE_KINDS = frozenset(
    {"lint", "compile", "simulation", "waveform", "formal", "equivalence", "synthesis", "sta", "coverage", "mutation"}
)
RUN_EVIDENCE_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "status",
        "tool",
        "input_hash",
        "subject_hashes",
        "commands",
        "artifacts",
        "artifact_hashes",
        "top",
        "claim_scope",
        "evidence_file",
        "started_at",
        "finished_at",
        "summary",
    }
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
OBSERVATION_STATUSES = frozenset({"fail", "timeout", "blocked"})


def normalize_evidence_kinds(kinds: Iterable[str]) -> tuple[str, ...]:
    values = tuple(kinds)
    if any(not isinstance(kind, str) or kind not in EVIDENCE_KINDS for kind in values):
        raise RtlAssError(
            "invalid_evidence_kind",
            "verification policy contains an unsupported evidence kind",
            {"kinds": list(values), "supported": sorted(EVIDENCE_KINDS)},
        )
    if len(set(values)) != len(values):
        raise RtlAssError("duplicate_evidence_kind", "verification policy contains duplicate evidence kinds")
    return tuple(sorted(values))


def build_verification_gate(
    evidence_items: Sequence[Mapping[str, Any]],
    *,
    content_hash: str,
    required_evidence_kinds: Iterable[str] = (),
    require_current_artifacts: bool = False,
) -> dict[str, Any]:
    if not _SHA256.fullmatch(content_hash):
        raise RtlAssError("invalid_content_hash", "candidate content hash must be SHA-256")
    if not evidence_items:
        raise RtlAssError("verification_required", "candidate verification requires non-empty evidence")
    required_kinds = normalize_evidence_kinds(required_evidence_kinds)
    observed_kinds: set[str] = set()
    seen_evidence: set[tuple[str, str]] = set()
    normalized_items: list[dict[str, Any]] = []
    for index, item in enumerate(evidence_items):
        normalized = _validate_run_evidence(
            item,
            content_hash=content_hash,
            index=index,
            require_current_artifacts=require_current_artifacts,
            allowed_statuses=frozenset({"pass"}),
        )
        identity = (normalized["kind"], normalized["input_hash"])
        if identity in seen_evidence:
            raise RtlAssError(
                "duplicate_evidence",
                "verification gate contains duplicate run evidence",
                {"index": index, "kind": identity[0], "input_hash": identity[1]},
            )
        seen_evidence.add(identity)
        observed_kinds.add(normalized["kind"])
        normalized_items.append(normalized)
    missing_kinds = sorted(set(required_kinds).difference(observed_kinds))
    if missing_kinds:
        raise RtlAssError(
            "evidence_gate_unsatisfied",
            "verification evidence does not satisfy the configured gate",
            {
                "required_kinds": list(required_kinds),
                "observed_kinds": sorted(observed_kinds),
                "missing_kinds": missing_kinds,
            },
        )
    return {
        "schema_version": "1.0",
        "gate_status": "pass",
        "required_kinds": list(required_kinds),
        "observed_kinds": sorted(observed_kinds),
        "evidence": normalized_items,
    }


def build_observation_set(
    evidence_items: Sequence[Mapping[str, Any]],
    *,
    content_hash: str,
    require_current_artifacts: bool = False,
) -> dict[str, Any]:
    if not _SHA256.fullmatch(content_hash):
        raise RtlAssError("invalid_content_hash", "observation target content hash must be SHA-256")
    if not evidence_items:
        raise RtlAssError("observation_required", "recording an observation requires non-empty evidence")
    seen_evidence: set[tuple[str, str, str]] = set()
    normalized_items: list[dict[str, Any]] = []
    for index, item in enumerate(evidence_items):
        normalized = _validate_run_evidence(
            item,
            content_hash=content_hash,
            index=index,
            require_current_artifacts=require_current_artifacts,
            allowed_statuses=OBSERVATION_STATUSES,
        )
        identity = (normalized["kind"], normalized["status"], normalized["input_hash"])
        if identity in seen_evidence:
            raise RtlAssError(
                "duplicate_evidence",
                "observation contains duplicate run evidence",
                {"index": index, "kind": identity[0], "status": identity[1], "input_hash": identity[2]},
            )
        seen_evidence.add(identity)
        normalized_items.append(normalized)
    return {
        "schema_version": "1.0",
        "observed_kinds": sorted({item["kind"] for item in normalized_items}),
        "observed_statuses": sorted({item["status"] for item in normalized_items}),
        "evidence": normalized_items,
    }


def validate_verification_gate(
    evidence: Mapping[str, Any] | None,
    content_hash: str,
    required_evidence_kinds: Iterable[str],
) -> None:
    if not evidence:
        raise RtlAssError("verification_required", "candidate verification requires computed gate evidence")
    items = evidence.get("evidence")
    if not isinstance(items, list) or not items:
        raise RtlAssError("verification_required", "candidate verification requires non-empty evidence")
    computed = build_verification_gate(
        items,
        content_hash=content_hash,
        required_evidence_kinds=required_evidence_kinds,
    )
    for field in ("schema_version", "gate_status", "required_kinds", "observed_kinds"):
        if evidence.get(field) != computed[field]:
            raise RtlAssError(
                "invalid_evidence_gate",
                "stored verification gate does not match centrally computed evidence",
                {"field": field, "expected": computed[field], "found": evidence.get(field)},
            )


def _validate_run_evidence(
    item: Mapping[str, Any],
    *,
    content_hash: str,
    index: int,
    require_current_artifacts: bool,
    allowed_statuses: frozenset[str],
) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise RtlAssError("invalid_evidence", "each evidence item must be an object", {"index": index})
    required = {
        "schema_version",
        "kind",
        "status",
        "tool",
        "input_hash",
        "subject_hashes",
        "commands",
        "artifacts",
        "artifact_hashes",
        "claim_scope",
        "evidence_file",
        "started_at",
        "finished_at",
        "summary",
    }
    missing = sorted(required.difference(item))
    if missing:
        raise RtlAssError(
            "invalid_evidence", "evidence item is missing required fields", {"index": index, "missing": missing}
        )
    unknown = sorted(set(item).difference(RUN_EVIDENCE_FIELDS))
    if unknown:
        raise RtlAssError(
            "invalid_evidence", "evidence item contains unsupported fields", {"index": index, "fields": unknown}
        )
    kind = item["kind"]
    input_hash = item["input_hash"]
    try:
        canonical_json(item)
    except (TypeError, ValueError) as exc:
        raise RtlAssError(
            "invalid_evidence", "run evidence must contain only finite JSON values", {"index": index}
        ) from exc
    if not isinstance(kind, str) or kind not in EVIDENCE_KINDS:
        raise RtlAssError("invalid_evidence_kind", "run evidence kind is unsupported", {"index": index, "kind": kind})
    if (
        item["schema_version"] != "1.0"
        or item["status"] not in allowed_statuses
        or not isinstance(input_hash, str)
        or not _SHA256.fullmatch(input_hash)
    ):
        raise RtlAssError(
            "invalid_evidence",
            "tool evidence has an unsupported schema, status, or input hash",
            {"index": index, "allowed_statuses": sorted(allowed_statuses)},
        )
    if item["claim_scope"] != "tool execution evidence only":
        raise RtlAssError(
            "invalid_evidence", "executed evidence must retain the tool-execution claim boundary", {"index": index}
        )
    tool = item["tool"]
    if (
        not isinstance(tool, dict)
        or set(tool) != {"name", "version"}
        or not all(isinstance(tool.get(field), str) and tool[field] for field in ("name", "version"))
    ):
        raise RtlAssError("invalid_evidence", "evidence tool must contain non-empty name and version", {"index": index})
    _validate_timestamps(item, index)
    if not isinstance(item["summary"], dict):
        raise RtlAssError("invalid_evidence", "evidence summary must be an object", {"index": index})
    commands = item["commands"]
    if (
        not isinstance(commands, list)
        or not commands
        or any(
            not isinstance(command, list)
            or not command
            or not all(isinstance(argument, str) and argument for argument in command)
            for command in commands
        )
    ):
        raise RtlAssError(
            "invalid_evidence", "executed tool evidence requires exact non-empty commands", {"index": index}
        )
    artifacts = item["artifacts"]
    if (
        not isinstance(artifacts, list)
        or not artifacts
        or not all(isinstance(path, str) and path for path in artifacts)
    ):
        raise RtlAssError("invalid_evidence", "executed evidence requires non-empty artifact paths", {"index": index})
    _validate_artifacts(item["artifact_hashes"], artifacts, index=index, require_current=require_current_artifacts)
    _validate_subjects(
        item["subject_hashes"],
        content_hash=content_hash,
        index=index,
        require_current=require_current_artifacts and item["status"] != "blocked",
    )
    _validate_evidence_file(item, index=index, require_current=require_current_artifacts)
    return dict(item)


def _validate_timestamps(item: Mapping[str, Any], index: int) -> None:
    timestamps: list[datetime] = []
    for field in ("started_at", "finished_at"):
        value = item[field]
        if not isinstance(value, str):
            raise RtlAssError(
                "invalid_evidence", "evidence timestamps must be strings", {"index": index, "field": field}
            )
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise RtlAssError(
                "invalid_evidence", "evidence timestamps must be ISO-8601", {"index": index, "field": field}
            ) from exc
        if parsed.tzinfo is None:
            raise RtlAssError(
                "invalid_evidence", "evidence timestamps must include a timezone", {"index": index, "field": field}
            )
        timestamps.append(parsed)
    if timestamps[1] < timestamps[0]:
        raise RtlAssError("invalid_evidence", "evidence finish time cannot precede its start time", {"index": index})


def _validate_artifacts(
    artifact_hashes: Any,
    artifacts: list[str],
    *,
    index: int,
    require_current: bool,
) -> None:
    if not isinstance(artifact_hashes, list) or len(artifact_hashes) != len(artifacts):
        raise RtlAssError("invalid_evidence", "artifact hashes must cover every artifact in order", {"index": index})
    for artifact_index, (artifact_path, artifact) in enumerate(zip(artifacts, artifact_hashes, strict=True)):
        artifact_hash = artifact.get("content_hash") if isinstance(artifact, dict) else None
        if (
            not isinstance(artifact, dict)
            or set(artifact) != {"index", "path", "content_hash"}
            or isinstance(artifact.get("index"), bool)
            or artifact.get("index") != artifact_index
            or artifact.get("path") != artifact_path
            or not isinstance(artifact_hash, str)
            or not _SHA256.fullmatch(artifact_hash)
        ):
            raise RtlAssError(
                "invalid_evidence",
                "artifact hashes require ordered indices, matching paths, and SHA-256 content hashes",
                {"index": index, "artifact_index": artifact_index},
            )
        if require_current:
            path = Path(artifact_path)
            if not path.is_file():
                raise RtlAssError(
                    "evidence_artifact_missing",
                    "verification artifact no longer exists",
                    {"index": index, "artifact_index": artifact_index, "path": artifact_path},
                )
            current_hash = hash_file(path)
            if current_hash != artifact_hash:
                raise RtlAssError(
                    "evidence_artifact_changed",
                    "verification artifact content no longer matches its evidence hash",
                    {
                        "index": index,
                        "artifact_index": artifact_index,
                        "path": artifact_path,
                        "expected": artifact_hash,
                        "found": current_hash,
                    },
                )


def _validate_subjects(
    subjects: Any,
    *,
    content_hash: str,
    index: int,
    require_current: bool,
) -> None:
    if not isinstance(subjects, list) or not subjects:
        raise RtlAssError("invalid_evidence", "evidence requires non-empty subject hashes", {"index": index})
    subject_content_hashes: set[str] = set()
    validated_subjects: list[tuple[int, str, str]] = []
    for subject_index, subject in enumerate(subjects):
        if not isinstance(subject, dict):
            raise RtlAssError(
                "invalid_evidence",
                "each evidence subject must be an object",
                {"index": index, "subject_index": subject_index},
            )
        subject_hash = subject.get("content_hash")
        subject_position = subject.get("index")
        if (
            set(subject) != {"index", "path", "content_hash"}
            or isinstance(subject_position, bool)
            or not isinstance(subject_position, int)
            or subject_position != subject_index
            or not isinstance(subject.get("path"), str)
            or not subject["path"]
            or not isinstance(subject_hash, str)
            or not _SHA256.fullmatch(subject_hash)
        ):
            raise RtlAssError(
                "invalid_evidence",
                "evidence subjects require ordered indices, non-empty paths, and SHA-256 content hashes",
                {"index": index, "subject_index": subject_index},
            )
        subject_content_hashes.add(subject_hash)
        validated_subjects.append((subject_index, subject["path"], subject_hash))
    if content_hash not in subject_content_hashes:
        raise RtlAssError(
            "evidence_input_mismatch",
            "verification evidence subjects do not include the candidate content",
            {"index": index, "expected_subject_hash": content_hash},
        )
    if require_current:
        for subject_index, subject_path, subject_hash in validated_subjects:
            path = Path(subject_path)
            if not path.is_file():
                raise RtlAssError(
                    "evidence_subject_missing",
                    "verification subject no longer exists",
                    {"index": index, "subject_index": subject_index, "path": subject_path},
                )
            current_hash = hash_file(path)
            if current_hash != subject_hash:
                raise RtlAssError(
                    "evidence_subject_changed",
                    "verification subject content no longer matches its evidence hash",
                    {
                        "index": index,
                        "subject_index": subject_index,
                        "path": subject_path,
                        "expected": subject_hash,
                        "found": current_hash,
                    },
                )


def _validate_evidence_file(item: Mapping[str, Any], *, index: int, require_current: bool) -> None:
    evidence_file = item["evidence_file"]
    if not isinstance(evidence_file, str) or not evidence_file:
        raise RtlAssError("invalid_evidence", "passing evidence requires an evidence file path", {"index": index})
    if not require_current:
        return
    path = Path(evidence_file)
    if not path.is_file():
        raise RtlAssError(
            "evidence_file_missing", "run-evidence JSON no longer exists", {"index": index, "path": evidence_file}
        )
    try:
        stored_evidence = parse_json(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise RtlAssError(
            "evidence_file_invalid",
            "run-evidence file is not valid UTF-8 JSON",
            {"index": index, "path": evidence_file},
        ) from exc
    if stored_evidence != item:
        raise RtlAssError(
            "evidence_file_changed",
            "run-evidence file content does not match the submitted evidence object",
            {"index": index, "path": evidence_file},
        )
