"""Strict, portable, license-aware knowledge-pack contracts."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from rtl_ass.errors import RtlAssError
from rtl_ass.integrity import canonical_json, hash_bytes, hash_json, parse_json
from rtl_ass.kb.models import LicenseStatus, LinkRelation, RecordRole, validate_identifier, validate_link_roles

MAX_PACK_BYTES = 10 * 1024 * 1024
MAX_PACK_RECORDS = 1000
MAX_PACK_CONTENT_BYTES = 2 * 1024 * 1024
_PACK_FIELDS = frozenset(
    {"schema_version", "name", "version", "description", "license_spdx", "records", "links", "pack_hash"}
)
_RECORD_FIELDS = frozenset(
    {
        "key",
        "role",
        "language",
        "title",
        "summary",
        "content_hash",
        "source_uri",
        "source_revision",
        "source_path",
        "license_spdx",
        "license_status",
        "metadata",
    }
)
_LINK_FIELDS = frozenset({"source", "target", "relation", "metadata"})
_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){0,2}(?:[-+][A-Za-z0-9.-]+)?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def load_knowledge_pack(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise RtlAssError("knowledge_pack_not_found", "knowledge pack JSON does not exist", {"path": str(source)})
    if source.stat().st_size > MAX_PACK_BYTES:
        raise RtlAssError(
            "knowledge_pack_too_large",
            "knowledge pack JSON exceeds the supported byte limit",
            {"max_bytes": MAX_PACK_BYTES},
        )
    try:
        value = parse_json(source.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise RtlAssError(
            "invalid_knowledge_pack", "knowledge pack must be finite UTF-8 JSON", {"reason": str(exc)}
        ) from exc
    return validate_knowledge_pack(value, base_directory=source.resolve().parent)


def validate_knowledge_pack(value: Any, *, base_directory: Path | None = None) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _PACK_FIELDS:
        raise RtlAssError("invalid_knowledge_pack", "knowledge pack root fields do not match the 1.0 contract")
    if value["schema_version"] != "1.0":
        raise RtlAssError("invalid_knowledge_pack", "knowledge pack schema_version must be 1.0")
    name = validate_identifier(value["name"], "pack.name")
    version = value["version"]
    description = value["description"]
    license_spdx = value["license_spdx"]
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise RtlAssError("invalid_knowledge_pack", "knowledge pack version must be a bounded semantic version")
    if not isinstance(description, str) or not description or len(description) > 4096:
        raise RtlAssError("invalid_knowledge_pack", "knowledge pack description must contain 1 to 4096 characters")
    if not isinstance(license_spdx, str) or not license_spdx or len(license_spdx) > 128:
        raise RtlAssError("invalid_knowledge_pack", "knowledge pack license_spdx must be non-empty")
    records = value["records"]
    links = value["links"]
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_PACK_RECORDS:
        raise RtlAssError(
            "invalid_knowledge_pack",
            f"knowledge pack must contain between 1 and {MAX_PACK_RECORDS} records",
        )
    if not isinstance(links, list):
        raise RtlAssError("invalid_knowledge_pack", "knowledge pack links must be an array")

    normalized_records: list[dict[str, Any]] = []
    roles: dict[str, RecordRole] = {}
    for index, record in enumerate(records):
        normalized = _validate_pack_record(record, index=index, base_directory=base_directory)
        key = normalized["key"]
        if key in roles:
            raise RtlAssError("duplicate_pack_record", "knowledge pack record keys must be unique", {"key": key})
        roles[key] = RecordRole(normalized["role"])
        normalized_records.append(normalized)

    normalized_links: list[dict[str, Any]] = []
    seen_links: set[tuple[str, str, str]] = set()
    for index, link in enumerate(links):
        normalized = _validate_pack_link(link, index=index, roles=roles)
        identity = (normalized["source"], normalized["target"], normalized["relation"])
        if identity in seen_links:
            raise RtlAssError("duplicate_pack_link", "knowledge pack links must be unique", {"index": index})
        seen_links.add(identity)
        normalized_links.append(normalized)

    normalized = {
        "schema_version": "1.0",
        "name": name,
        "version": version,
        "description": description,
        "license_spdx": license_spdx,
        "records": normalized_records,
        "links": normalized_links,
    }
    if not isinstance(value["pack_hash"], str) or not _SHA256.fullmatch(value["pack_hash"]):
        raise RtlAssError("invalid_knowledge_pack", "knowledge pack pack_hash must be lowercase SHA-256")
    expected_hash = knowledge_pack_hash(normalized)
    if value["pack_hash"] != expected_hash:
        raise RtlAssError(
            "knowledge_pack_hash_mismatch",
            "knowledge pack identity does not match its declared hash",
            {"expected": expected_hash, "found": value["pack_hash"]},
        )
    return {**normalized, "pack_hash": expected_hash}


def knowledge_pack_hash(pack: Mapping[str, Any]) -> str:
    records = []
    for record in pack["records"]:
        records.append({key: record[key] for key in sorted(_RECORD_FIELDS)})
    identity = {
        "schema_version": pack["schema_version"],
        "name": pack["name"],
        "version": pack["version"],
        "description": pack["description"],
        "license_spdx": pack["license_spdx"],
        "records": records,
        "links": pack["links"],
    }
    return hash_json(identity)


def write_knowledge_pack(pack: Mapping[str, Any], output_path: str | Path) -> Path:
    validated = validate_knowledge_pack(dict(pack))
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    payload = json.dumps(validated, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if len(payload.encode("utf-8")) > MAX_PACK_BYTES:
        raise RtlAssError("knowledge_pack_too_large", "exported knowledge pack exceeds the supported byte limit")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, destination)
    return destination


def build_export_pack(
    records: Sequence[Mapping[str, Any]],
    links: Sequence[Mapping[str, Any]],
    *,
    name: str,
    version: str,
    description: str,
    license_spdx: str,
) -> dict[str, Any]:
    exported_records = []
    for record in records:
        exported_records.append(
            {
                "key": record["id"],
                "role": record["role"],
                "language": record["language"],
                "title": record["title"],
                "summary": record["summary"],
                "content_hash": record["content_hash"],
                "source_uri": record["source_uri"],
                "source_revision": record["source_revision"],
                "source_path": record["source_path"],
                "license_spdx": record["license_spdx"],
                "license_status": record["license_status"],
                "metadata": record["metadata"],
                "content": record["content"],
            }
        )
    exported_links = [
        {
            "source": link["source_record_id"],
            "target": link["target_record_id"],
            "relation": link["relation"],
            "metadata": link["metadata"],
        }
        for link in links
    ]
    pack: dict[str, Any] = {
        "schema_version": "1.0",
        "name": name,
        "version": version,
        "description": description,
        "license_spdx": license_spdx,
        "records": exported_records,
        "links": exported_links,
    }
    pack["pack_hash"] = knowledge_pack_hash(pack)
    return validate_knowledge_pack(pack)


def _validate_pack_record(record: Any, *, index: int, base_directory: Path | None) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise RtlAssError("invalid_pack_record", "knowledge pack records must be objects", {"index": index})
    fields = set(record)
    content_fields = fields.intersection({"content", "content_path"})
    if (
        fields.difference({*_RECORD_FIELDS, "content", "content_path"})
        or fields.intersection(_RECORD_FIELDS) != _RECORD_FIELDS
    ):
        raise RtlAssError(
            "invalid_pack_record", "knowledge pack record fields do not match the 1.0 contract", {"index": index}
        )
    if len(content_fields) != 1:
        raise RtlAssError(
            "invalid_pack_record", "each pack record requires exactly one content or content_path", {"index": index}
        )
    validate_identifier(record["key"], "record.key")
    try:
        role = RecordRole(record["role"])
        license_status = LicenseStatus(record["license_status"])
    except (TypeError, ValueError) as exc:
        raise RtlAssError(
            "invalid_pack_record", "pack record role or license status is unsupported", {"index": index}
        ) from exc
    if role is RecordRole.TOOL_EVIDENCE:
        raise RtlAssError("invalid_pack_record", "tool-evidence records are not portable knowledge-pack content")
    for field, maximum in (("language", 64), ("title", 512), ("summary", 4096), ("license_spdx", 128)):
        value = record[field]
        if not isinstance(value, str) or not value or len(value) > maximum:
            raise RtlAssError("invalid_pack_record", f"pack record {field} is invalid", {"index": index})
    for field in ("source_uri", "source_revision", "source_path"):
        if not isinstance(record[field], str) or len(record[field]) > 4096:
            raise RtlAssError("invalid_pack_record", f"pack record {field} is invalid", {"index": index})
    if not isinstance(record["metadata"], dict):
        raise RtlAssError("invalid_pack_record", "pack record metadata must be an object", {"index": index})
    try:
        canonical_json(record["metadata"])
    except (TypeError, ValueError) as exc:
        raise RtlAssError("invalid_pack_record", "pack record metadata must be finite JSON", {"index": index}) from exc
    if not isinstance(record["content_hash"], str) or not _SHA256.fullmatch(record["content_hash"]):
        raise RtlAssError("invalid_pack_record", "pack record content_hash must be lowercase SHA-256", {"index": index})
    content = _record_content(record, base_directory=base_directory, index=index)
    content_hash = hash_bytes(content.encode("utf-8"))
    if record["content_hash"] != content_hash:
        raise RtlAssError(
            "pack_content_hash_mismatch",
            "pack record content does not match its declared hash",
            {"index": index, "expected": content_hash, "found": record["content_hash"]},
        )
    return {
        **{field: record[field] for field in _RECORD_FIELDS},
        "role": role.value,
        "license_status": license_status.value,
        "content": content,
    }


def _record_content(record: Mapping[str, Any], *, base_directory: Path | None, index: int) -> str:
    if "content" in record:
        content = record["content"]
        if not isinstance(content, str):
            raise RtlAssError("invalid_pack_record", "embedded pack content must be text", {"index": index})
    else:
        relative = record["content_path"]
        if base_directory is None or not isinstance(relative, str) or not relative:
            raise RtlAssError(
                "invalid_pack_record", "content_path requires a pack file base directory", {"index": index}
            )
        candidate = (base_directory / relative).resolve()
        if candidate != base_directory and base_directory not in candidate.parents:
            raise RtlAssError("pack_path_escape", "pack content_path escapes the pack directory", {"index": index})
        if not candidate.is_file():
            raise RtlAssError("pack_content_not_found", "pack content_path does not identify a file", {"index": index})
        try:
            content = candidate.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise RtlAssError("invalid_pack_record", "pack content files must be UTF-8", {"index": index}) from exc
    if not content or len(content.encode("utf-8")) > MAX_PACK_CONTENT_BYTES:
        raise RtlAssError(
            "invalid_pack_record",
            f"pack record content must contain 1 to {MAX_PACK_CONTENT_BYTES} UTF-8 bytes",
            {"index": index},
        )
    return content


def _validate_pack_link(link: Any, *, index: int, roles: Mapping[str, RecordRole]) -> dict[str, Any]:
    if not isinstance(link, dict) or set(link) != _LINK_FIELDS:
        raise RtlAssError(
            "invalid_pack_link", "knowledge pack link fields do not match the 1.0 contract", {"index": index}
        )
    source = link["source"]
    target = link["target"]
    if source == target or source not in roles or target not in roles:
        raise RtlAssError(
            "invalid_pack_link", "pack link must reference two distinct pack record keys", {"index": index}
        )
    try:
        relation = LinkRelation(link["relation"])
    except (TypeError, ValueError) as exc:
        raise RtlAssError("invalid_pack_link", "pack link relation is unsupported", {"index": index}) from exc
    if not isinstance(link["metadata"], dict):
        raise RtlAssError("invalid_pack_link", "pack link metadata must be an object", {"index": index})
    try:
        canonical_json(link["metadata"])
    except (TypeError, ValueError) as exc:
        raise RtlAssError("invalid_pack_link", "pack link metadata must be finite JSON", {"index": index}) from exc
    validate_link_roles(relation, roles[source], roles[target])
    return {"source": source, "target": target, "relation": relation.value, "metadata": dict(link["metadata"])}
