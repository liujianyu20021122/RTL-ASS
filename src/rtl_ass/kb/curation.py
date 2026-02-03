"""Transactional derivation and portable knowledge-pack workflows."""

from __future__ import annotations

import sqlite3
from typing import Any, Mapping, Sequence

from rtl_ass.errors import RtlAssError
from rtl_ass.kb.models import KnowledgeRecordInput, LicenseStatus, LinkRelation, RecordRole, RecordStatus
from rtl_ass.kb.packs import build_export_pack
from rtl_ass.kb.record_store import DatabaseRecordStore, database_json

DERIVATION_METHODS = frozenset({"extract", "generalize", "normalize", "repair", "summarize"})
DERIVABLE_ROLES = frozenset(RecordRole) - frozenset({RecordRole.TOOL_EVIDENCE})


def derive_record(
    store: DatabaseRecordStore,
    connection: sqlite3.Connection,
    source_record_id: str,
    *,
    namespace: str,
    role: RecordRole,
    language: str,
    title: str,
    summary: str,
    content: str,
    source_path: str,
    method: str,
    actor: str,
) -> dict[str, Any]:
    if role not in DERIVABLE_ROLES:
        raise RtlAssError("invalid_derivation_role", "tool evidence cannot be authored through knowledge derivation")
    if method not in DERIVATION_METHODS:
        raise RtlAssError("invalid_derivation_method", "knowledge derivation method is unsupported", {"method": method})
    source = store._get_record(connection, source_record_id, include_content=True)
    if RecordRole(source["role"]) is RecordRole.TOOL_EVIDENCE:
        raise RtlAssError("invalid_derivation_source", "tool evidence cannot be the sole source of a distilled record")
    record = KnowledgeRecordInput(
        namespace=namespace,
        role=role,
        language=language,
        title=title,
        summary=summary,
        content=content,
        source_uri=source["source_uri"],
        source_revision=source["source_revision"],
        source_path=source_path,
        license_spdx=source["license_spdx"],
        license_status=LicenseStatus(source["license_status"]),
        status=RecordStatus.CANDIDATE,
        metadata={
            "derivation": {
                "method": method,
                "source_record_id": source["id"],
                "source_content_hash": source["content_hash"],
            }
        },
    )
    stored = store._insert_record(connection, record, actor=actor)
    link_metadata = {"method": method, "source_content_hash": source["content_hash"]}
    link = _ensure_link(
        store,
        connection,
        stored["record"]["id"],
        source["id"],
        LinkRelation.DERIVED_FROM,
        actor=actor,
        metadata=link_metadata,
    )
    return {
        "schema_version": "1.0",
        "created": stored["created"],
        "source": {"id": source["id"], "content_hash": source["content_hash"]},
        "record": stored["record"],
        "link": link,
    }


def import_pack(
    store: DatabaseRecordStore,
    connection: sqlite3.Connection,
    pack: Mapping[str, Any],
    *,
    namespace: str,
    actor: str,
) -> dict[str, Any]:
    records_by_key: dict[str, dict[str, Any]] = {}
    created_count = 0
    for item in pack["records"]:
        record = KnowledgeRecordInput(
            namespace=namespace,
            role=RecordRole(item["role"]),
            language=item["language"],
            title=item["title"],
            summary=item["summary"],
            content=item["content"],
            source_uri=item["source_uri"],
            source_revision=item["source_revision"],
            source_path=item["source_path"],
            license_spdx=item["license_spdx"],
            license_status=LicenseStatus(item["license_status"]),
            status=RecordStatus.RAW,
            metadata={
                **item["metadata"],
                "knowledge_pack": {
                    "name": pack["name"],
                    "version": pack["version"],
                    "pack_hash": pack["pack_hash"],
                    "record_key": item["key"],
                },
            },
        )
        stored = store._insert_record(connection, record, actor=actor)
        created_count += int(stored["created"])
        records_by_key[item["key"]] = stored["record"]
    imported_links = []
    for item in pack["links"]:
        source = records_by_key[item["source"]]
        target = records_by_key[item["target"]]
        imported_links.append(
            _ensure_link(
                store,
                connection,
                source["id"],
                target["id"],
                LinkRelation(item["relation"]),
                actor=actor,
                metadata={**item["metadata"], "pack_hash": pack["pack_hash"]},
            )
        )
    return {
        "schema_version": "1.0",
        "pack": {"name": pack["name"], "version": pack["version"], "pack_hash": pack["pack_hash"]},
        "namespace": namespace,
        "record_count": len(records_by_key),
        "created_count": created_count,
        "records": [records_by_key[item["key"]] for item in pack["records"]],
        "links": imported_links,
    }


def export_pack(
    store: DatabaseRecordStore,
    connection: sqlite3.Connection,
    record_ids: Sequence[str],
    *,
    name: str,
    version: str,
    description: str,
    license_spdx: str,
) -> dict[str, Any]:
    if not record_ids or len(set(record_ids)) != len(record_ids):
        raise RtlAssError("invalid_pack_selection", "pack export requires unique explicit record IDs")
    records = [store._get_record(connection, record_id, include_content=True) for record_id in record_ids]
    blocked = [
        record["id"]
        for record in records
        if LicenseStatus(record["license_status"]) is not LicenseStatus.KNOWN
        or record["license_spdx"].upper() == "UNKNOWN"
    ]
    if blocked:
        raise RtlAssError(
            "pack_license_blocked",
            "knowledge pack export requires explicit known redistribution licensing",
            {"record_ids": blocked},
        )
    selected = set(record_ids)
    rows = connection.execute(
        """
        SELECT id, source_record_id, target_record_id, relation, metadata_json, created_at
        FROM record_links
        ORDER BY id
        """
    ).fetchall()
    links = [
        {
            **{key: row[key] for key in ("source_record_id", "target_record_id", "relation")},
            "metadata": database_json(row["metadata_json"], "record_links.metadata_json"),
        }
        for row in rows
        if row["source_record_id"] in selected and row["target_record_id"] in selected
    ]
    return build_export_pack(
        records,
        links,
        name=name,
        version=version,
        description=description,
        license_spdx=license_spdx,
    )


def _ensure_link(
    store: DatabaseRecordStore,
    connection: sqlite3.Connection,
    source_record_id: str,
    target_record_id: str,
    relation: LinkRelation,
    *,
    actor: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT id, metadata_json FROM record_links
        WHERE source_record_id = ? AND target_record_id = ? AND relation = ?
        """,
        (source_record_id, target_record_id, relation.value),
    ).fetchone()
    if row is None:
        return store._insert_link(
            connection,
            source_record_id,
            target_record_id,
            relation,
            actor=actor,
            metadata=metadata,
        )
    if database_json(row["metadata_json"], "record_links.metadata_json") != dict(metadata):
        raise RtlAssError("knowledge_link_conflict", "an existing knowledge link has conflicting metadata")
    return {
        "id": row["id"],
        "source_record_id": source_record_id,
        "target_record_id": target_record_id,
        "relation": relation.value,
    }
