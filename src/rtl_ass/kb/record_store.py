"""Transactional record, link, and lifecycle persistence primitives."""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable, Mapping

from rtl_ass.errors import RtlAssError
from rtl_ass.integrity import canonical_json, parse_json, utc_now
from rtl_ass.kb.audit import append_audit
from rtl_ass.kb.models import (
    KnowledgeRecordInput,
    LicenseStatus,
    LinkRelation,
    RecordRole,
    RecordStatus,
    validate_link_roles,
    validate_transition,
)


def database_json(value: str, field: str) -> Any:
    try:
        return parse_json(value)
    except (TypeError, ValueError) as exc:
        raise RtlAssError(
            "database_json_invalid",
            "knowledge database contains invalid finite JSON",
            {"field": field},
        ) from exc


def row_dict(row: sqlite3.Row, *, include_content: bool = False) -> dict[str, Any]:
    result = dict(row)
    for field in ("metadata_json", "verification_json"):
        if field in result:
            result[field.removesuffix("_json")] = database_json(result.pop(field), field)
    if not include_content:
        result.pop("content", None)
    return result


class DatabaseRecordStore:
    @staticmethod
    def _get_record(
        connection: sqlite3.Connection,
        record_id: str,
        *,
        include_content: bool = False,
    ) -> dict[str, Any]:
        row = connection.execute(
            """
            SELECT r.*, b.content
            FROM records AS r JOIN blobs AS b ON b.content_hash = r.content_hash
            WHERE r.id = ?
            """,
            (record_id,),
        ).fetchone()
        if row is None:
            raise RtlAssError("record_not_found", "knowledge record was not found", {"record_id": record_id})
        return row_dict(row, include_content=include_content)

    @classmethod
    def _insert_record(
        cls,
        connection: sqlite3.Connection,
        record: KnowledgeRecordInput,
        *,
        actor: str,
    ) -> dict[str, Any]:
        record.validate()
        existing = connection.execute("SELECT id FROM records WHERE id = ?", (record.identity,)).fetchone()
        if existing is not None:
            stored = cls._get_record(connection, record.identity, include_content=True)
            expected_immutable = {
                "namespace": record.namespace,
                "role": record.role.value,
                "language": record.language,
                "title": record.title.strip(),
                "summary": record.summary,
                "content_hash": record.content_hash,
                "content": record.content,
                "source_uri": record.source_uri,
                "source_revision": record.source_revision,
                "source_path": record.source_path,
                "license_spdx": record.license_spdx,
                "license_status": record.license_status.value,
                "metadata": dict(record.metadata),
            }
            conflicts = sorted(field for field, expected in expected_immutable.items() if stored[field] != expected)
            if conflicts:
                raise RtlAssError(
                    "record_identity_conflict",
                    "an existing knowledge identity has different immutable record fields",
                    {"record_id": record.identity, "fields": conflicts},
                )
            stored.pop("content", None)
            return {"created": False, "record": stored}
        now = utc_now()
        connection.execute(
            "INSERT OR IGNORE INTO blobs(content_hash, content, byte_count, created_at) VALUES(?, ?, ?, ?)",
            (record.content_hash, record.content, len(record.content.encode("utf-8")), now),
        )
        connection.execute(
            """
            INSERT INTO records(
                id, namespace, role, status, language, title, summary, content_hash,
                source_uri, source_revision, source_path, license_spdx, license_status,
                metadata_json, verification_json, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.identity,
                record.namespace,
                record.role.value,
                record.status.value,
                record.language,
                record.title.strip(),
                record.summary,
                record.content_hash,
                record.source_uri,
                record.source_revision,
                record.source_path,
                record.license_spdx,
                record.license_status.value,
                canonical_json(record.metadata),
                canonical_json(record.verification),
                now,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO records_fts(record_id, title, summary, content) VALUES(?, ?, ?, ?)",
            (record.identity, record.title.strip(), record.summary, record.content),
        )
        output = {
            "id": record.identity,
            "content_hash": record.content_hash,
            "status": record.status.value,
            "namespace": record.namespace,
            "role": record.role.value,
        }
        append_audit(
            connection,
            actor=actor,
            action="record.create",
            subject_type="record",
            subject_id=record.identity,
            previous_state=None,
            new_state=record.status.value,
            inputs={"content_hash": record.content_hash, "source_revision": record.source_revision},
            outputs=output,
            details={"source_uri": record.source_uri, "source_path": record.source_path},
        )
        return {"created": True, "record": cls._get_record(connection, record.identity)}

    @classmethod
    def _insert_link(
        cls,
        connection: sqlite3.Connection,
        source_record_id: str,
        target_record_id: str,
        relation: LinkRelation,
        *,
        actor: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if source_record_id == target_record_id:
            raise RtlAssError("self_link", "a knowledge record cannot link to itself")
        details = dict(metadata or {})
        rows = connection.execute(
            "SELECT id, role FROM records WHERE id IN (?, ?)",
            (source_record_id, target_record_id),
        ).fetchall()
        roles = {row["id"]: RecordRole(row["role"]) for row in rows}
        missing = [record_id for record_id in (source_record_id, target_record_id) if record_id not in roles]
        if missing:
            raise RtlAssError("record_not_found", "link references unknown records", {"record_ids": missing})
        validate_link_roles(relation, roles[source_record_id], roles[target_record_id])
        try:
            cursor = connection.execute(
                """
                INSERT INTO record_links(source_record_id, target_record_id, relation, metadata_json, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (source_record_id, target_record_id, relation.value, canonical_json(details), utc_now()),
            )
        except sqlite3.IntegrityError as exc:
            raise RtlAssError("duplicate_link", "the knowledge link already exists") from exc
        output = {
            "id": cursor.lastrowid,
            "source_record_id": source_record_id,
            "target_record_id": target_record_id,
            "relation": relation.value,
        }
        append_audit(
            connection,
            actor=actor,
            action="link.create",
            subject_type="link",
            subject_id=str(cursor.lastrowid),
            previous_state=None,
            new_state="active",
            inputs={"source": source_record_id, "target": target_record_id, "relation": relation.value},
            outputs=output,
            details=details,
        )
        return output

    @classmethod
    def _insert_observation_link(
        cls,
        connection: sqlite3.Connection,
        source_record_id: str,
        target_record_id: str,
        relation: LinkRelation,
        *,
        actor: str,
        metadata: Mapping[str, Any],
    ) -> dict[str, Any]:
        rows = connection.execute(
            """
            SELECT id, relation, metadata_json
            FROM record_links
            WHERE source_record_id = ? AND target_record_id = ?
              AND relation IN (?, ?)
            ORDER BY id
            """,
            (
                source_record_id,
                target_record_id,
                LinkRelation.NEGATIVE_FOR.value,
                LinkRelation.EVIDENCE_FOR.value,
            ),
        ).fetchall()
        for row in rows:
            stored_metadata = database_json(row["metadata_json"], "record_links.metadata_json")
            if row["relation"] == relation.value and stored_metadata == dict(metadata):
                return {
                    "id": row["id"],
                    "source_record_id": source_record_id,
                    "target_record_id": target_record_id,
                    "relation": relation.value,
                }
        if rows:
            raise RtlAssError(
                "observation_attribution_conflict",
                "the same evidence and target already have a different recorded attribution",
                {"source_record_id": source_record_id, "target_record_id": target_record_id},
            )
        return cls._insert_link(
            connection,
            source_record_id,
            target_record_id,
            relation,
            actor=actor,
            metadata=metadata,
        )

    @classmethod
    def _transition_record(
        cls,
        connection: sqlite3.Connection,
        record_id: str,
        target: RecordStatus,
        *,
        actor: str,
        evidence: Mapping[str, Any] | None,
        required_evidence_kinds: Iterable[str],
    ) -> dict[str, Any]:
        requirements = tuple(required_evidence_kinds)
        row = connection.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            raise RtlAssError("record_not_found", "knowledge record was not found", {"record_id": record_id})
        current = RecordStatus(row["status"])
        validate_transition(
            current,
            target,
            evidence=evidence,
            content_hash=row["content_hash"],
            license_status=LicenseStatus(row["license_status"]),
            license_spdx=row["license_spdx"],
            required_evidence_kinds=requirements,
        )
        verification = (
            evidence
            if evidence is not None
            else database_json(
                row["verification_json"],
                "records.verification_json",
            )
        )
        now = utc_now()
        connection.execute(
            "UPDATE records SET status = ?, verification_json = ?, updated_at = ? WHERE id = ?",
            (target.value, canonical_json(verification), now, record_id),
        )
        output = {"id": record_id, "status": target.value, "updated_at": now}
        append_audit(
            connection,
            actor=actor,
            action="record.transition",
            subject_type="record",
            subject_id=record_id,
            previous_state=current.value,
            new_state=target.value,
            inputs={"evidence": evidence or {}},
            outputs=output,
            details={"required_evidence_kinds": list(requirements)},
        )
        return cls._get_record(connection, record_id)
