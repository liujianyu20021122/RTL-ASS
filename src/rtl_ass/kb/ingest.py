"""Safe ingestion of Verilog and SystemVerilog source records."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rtl_ass.kb.database import KnowledgeDatabase
from rtl_ass.kb.models import KnowledgeRecordInput, LicenseStatus, RecordRole, RecordStatus
from rtl_ass.project import analyze_source, discover_sources


def ingest_path(
    database: KnowledgeDatabase,
    path: str | Path,
    *,
    namespace: str,
    actor: str,
    role_override: RecordRole | None = None,
    source_uri: str = "",
    source_revision: str = "",
    license_spdx: str = "UNKNOWN",
    license_status: LicenseStatus = LicenseStatus.UNKNOWN,
    initial_status: RecordStatus = RecordStatus.RAW,
    max_source_bytes: int = 5 * 1024 * 1024,
) -> dict[str, Any]:
    root = Path(path).resolve()
    base = root.parent if root.is_file() else root
    records: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for source_path in discover_sources(root):
        relative = source_path.relative_to(base).as_posix()
        size = source_path.stat().st_size
        if size > max_source_bytes:
            skipped.append({"path": relative, "reason": "source_too_large", "byte_count": size})
            continue
        try:
            text = source_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            skipped.append({"path": relative, "reason": "not_utf8", "offset": exc.start})
            continue
        analysis = analyze_source(source_path, text, relative)
        role = role_override or RecordRole(analysis["role"])
        named_units = analysis["modules"] or analysis["interfaces"] or analysis["packages"]
        title = ", ".join(named_units) if named_units else relative
        summary = f"{analysis['language']} {role.value} from {relative}"
        record = KnowledgeRecordInput(
            namespace=namespace,
            role=role,
            language=analysis["language"],
            title=title,
            summary=summary,
            content=text,
            source_uri=source_uri,
            source_revision=source_revision,
            source_path=relative,
            license_spdx=license_spdx,
            license_status=license_status,
            status=initial_status,
            metadata={"inspection": analysis},
        )
        result = database.add_record(record, actor=actor)
        records.append(
            {
                "id": result["record"]["id"],
                "created": result["created"],
                "path": relative,
                "role": role.value,
                "content_hash": result["record"]["content_hash"],
            }
        )
    return {
        "schema_version": "1.0",
        "namespace": namespace,
        "record_count": len(records),
        "created_count": sum(record["created"] for record in records),
        "records": records,
        "skipped": skipped,
    }
