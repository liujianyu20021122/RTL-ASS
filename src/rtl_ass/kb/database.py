"""Transactional SQLite knowledge store with append-only auditing."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping

from rtl_ass.errors import RtlAssError
from rtl_ass.kb.audit import append_audit, verify_audit_chain
from rtl_ass.kb.curation import derive_record as derive_record_workflow
from rtl_ass.kb.curation import export_pack as export_pack_workflow
from rtl_ass.kb.curation import import_pack as import_pack_workflow
from rtl_ass.kb.evidence_records import build_tool_evidence_record
from rtl_ass.kb.gates import build_observation_set, build_verification_gate
from rtl_ass.kb.migrations import migrate_v1_to_v2
from rtl_ass.kb.models import (
    KnowledgeRecordInput,
    LinkRelation,
    ObservationAttribution,
    RecordRole,
    RecordStatus,
    validate_identifier,
)
from rtl_ass.kb.packs import load_knowledge_pack
from rtl_ass.kb.record_store import DatabaseRecordStore, database_json, row_dict
from rtl_ass.kb.schema import (
    SCHEMA_SQL,
    SCHEMA_VERSION,
    create_audit_triggers,
    read_schema_version,
    require_current_schema,
)

_SEARCH_TOKEN = re.compile(r"[\w.$:/+-]+", re.UNICODE)


def _fts_expression(query: str, match_mode: str) -> str:
    tokens = _SEARCH_TOKEN.findall(query)
    if not tokens:
        raise RtlAssError("empty_search", "search query must contain at least one searchable token")
    if match_mode not in {"all", "any"}:
        raise RtlAssError("invalid_match_mode", "search match mode must be 'all' or 'any'")
    operator = " AND " if match_mode == "all" else " OR "
    return operator.join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


class KnowledgeDatabase(DatabaseRecordStore):
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self, actor: str = "rtl-ass") -> dict[str, Any]:
        validate_identifier(actor, "actor")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            existing_tables = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
            if "metadata" in existing_tables:
                version = read_schema_version(connection)
                if version != SCHEMA_VERSION:
                    raise RtlAssError(
                        "schema_version_mismatch",
                        "knowledge database schema version is unsupported",
                        {"found": version, "expected": SCHEMA_VERSION},
                    )
                return {"created": False, "schema_version": version, "database": str(self.path)}
            if existing_tables:
                raise RtlAssError(
                    "database_not_empty",
                    "refusing to initialize a database that contains an unknown schema",
                    {"tables": sorted(existing_tables)},
                )
            try:
                connection.executescript(f"BEGIN IMMEDIATE;\n{SCHEMA_SQL}")
                create_audit_triggers(connection)
            except sqlite3.OperationalError as exc:
                connection.rollback()
                raise RtlAssError(
                    "sqlite_capability_error", "SQLite with FTS5 is required", {"reason": str(exc)}
                ) from exc

            details = {"schema_version": SCHEMA_VERSION}
            connection.execute("INSERT INTO metadata(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
            append_audit(
                connection,
                actor=actor,
                action="database.initialize",
                subject_type="database",
                subject_id=self.path.name,
                previous_state=None,
                new_state=str(SCHEMA_VERSION),
                inputs={"path_name": self.path.name},
                outputs=details,
                details=details,
            )
            return {"created": True, "schema_version": SCHEMA_VERSION, "database": str(self.path)}

    def migrate(self, actor: str = "rtl-ass") -> dict[str, Any]:
        validate_identifier(actor, "actor")
        if not self.path.is_file():
            raise RtlAssError(
                "database_not_initialized", "run `rtl-ass kb init` before migrating the knowledge database"
            )
        connection = self._connect()
        try:
            current = read_schema_version(connection)
            if current == SCHEMA_VERSION:
                return {
                    "migrated": False,
                    "from_version": current,
                    "to_version": current,
                    "database": str(self.path),
                }
            if current != 1:
                raise RtlAssError(
                    "unsupported_migration",
                    "no verified migration path exists for this database schema",
                    {"found": current, "supported_from": [1], "target": SCHEMA_VERSION},
                )
            connection.execute("BEGIN IMMEDIATE")
            migrate_v1_to_v2(connection, actor=actor)
            audit_result = verify_audit_chain(connection)
            if not audit_result["valid"]:
                raise RtlAssError(
                    "migration_audit_invalid",
                    "migrated audit chain failed verification",
                    audit_result,
                )
            connection.commit()
        except RtlAssError:
            connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            connection.rollback()
            raise RtlAssError("migration_failed", "SQLite rejected the schema migration", {"reason": str(exc)}) from exc
        finally:
            connection.close()
        return {
            "migrated": True,
            "from_version": 1,
            "to_version": SCHEMA_VERSION,
            "database": str(self.path),
            "audit_chain": audit_result,
        }

    def add_record(self, record: KnowledgeRecordInput, actor: str = "rtl-ass") -> dict[str, Any]:
        validate_identifier(actor, "actor")
        with self._connect() as connection:
            self._require_schema(connection)
            return self._insert_record(connection, record, actor=actor)

    def add_records(
        self,
        records: Iterable[KnowledgeRecordInput],
        *,
        actor: str = "rtl-ass",
    ) -> list[dict[str, Any]]:
        """Insert a bounded caller-owned batch in one database transaction."""
        validate_identifier(actor, "actor")
        items = tuple(records)
        with self._connect() as connection:
            self._require_schema(connection)
            stored = [self._insert_record(connection, record, actor=actor) for record in items]
            audit = verify_audit_chain(connection)
            if not audit["valid"]:
                raise RtlAssError("batch_audit_invalid", "audit chain failed before batch commit", audit)
            return stored

    def derive_record(
        self,
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
        validate_identifier(actor, "actor")
        validate_identifier(namespace, "namespace")
        with self._connect() as connection:
            self._require_schema(connection)
            return derive_record_workflow(
                self,
                connection,
                source_record_id,
                namespace=namespace,
                role=role,
                language=language,
                title=title,
                summary=summary,
                content=content,
                source_path=source_path,
                method=method,
                actor=actor,
            )

    def import_pack(self, path: str | Path, *, namespace: str, actor: str) -> dict[str, Any]:
        validate_identifier(actor, "actor")
        validate_identifier(namespace, "namespace")
        pack = load_knowledge_pack(path)
        with self._connect() as connection:
            self._require_schema(connection)
            return import_pack_workflow(self, connection, pack, namespace=namespace, actor=actor)

    def export_pack(
        self,
        record_ids: Iterable[str],
        *,
        name: str,
        version: str,
        description: str,
        license_spdx: str,
    ) -> dict[str, Any]:
        identifiers = tuple(record_ids)
        with self._connect() as connection:
            self._require_schema(connection)
            return export_pack_workflow(
                self,
                connection,
                identifiers,
                name=name,
                version=version,
                description=description,
                license_spdx=license_spdx,
            )

    def get_record(self, record_id: str, *, include_content: bool = False) -> dict[str, Any]:
        with self._connect() as connection:
            self._require_schema(connection)
            return self._get_record(connection, record_id, include_content=include_content)

    def search(
        self,
        query: str,
        *,
        namespaces: Iterable[str],
        limit: int = 5,
        role: RecordRole | None = None,
        status: RecordStatus | None = None,
        match_mode: str = "all",
    ) -> list[dict[str, Any]]:
        namespace_values = tuple(namespaces)
        if not namespace_values:
            raise RtlAssError("namespace_required", "search requires at least one explicit namespace")
        for namespace in namespace_values:
            validate_identifier(namespace, "namespace")
        if limit < 1 or limit > 50:
            raise RtlAssError("invalid_limit", "search limit must be between 1 and 50", {"limit": limit})

        expression = _fts_expression(query, match_mode)
        namespace_slots = ",".join("?" for _ in namespace_values)
        filters = [f"r.namespace IN ({namespace_slots})"]
        parameters: list[Any] = [expression, *namespace_values]
        if role is not None:
            filters.append("r.role = ?")
            parameters.append(role.value)
        if status is not None:
            filters.append("r.status = ?")
            parameters.append(status.value)
        parameters.append(limit)
        sql = f"""
            SELECT r.id, r.namespace, r.role, r.status, r.language, r.title, r.summary,
                   r.content_hash, r.source_uri, r.source_revision, r.source_path,
                   r.license_spdx, r.license_status, r.metadata_json, r.verification_json,
                   r.created_at, r.updated_at,
                   snippet(records_fts, 3, '[', ']', '…', 20) AS excerpt,
                   bm25(records_fts) AS rank
            FROM records_fts JOIN records AS r ON r.id = records_fts.record_id
            WHERE records_fts MATCH ? AND {" AND ".join(filters)}
            ORDER BY
                CASE r.status
                    WHEN 'promoted' THEN 0
                    WHEN 'verified' THEN 1
                    WHEN 'candidate' THEN 2
                    WHEN 'analyzed' THEN 3
                    WHEN 'raw' THEN 4
                    ELSE 5
                END,
                rank,
                r.id
            LIMIT ?
        """
        with self._connect() as connection:
            self._require_schema(connection)
            rows = connection.execute(sql, parameters).fetchall()
            return [row_dict(row) for row in rows]

    def transition(
        self,
        record_id: str,
        target: RecordStatus,
        *,
        actor: str,
    ) -> dict[str, Any]:
        validate_identifier(actor, "actor")
        if target is RecordStatus.VERIFIED:
            raise RtlAssError(
                "verification_workflow_required",
                "use verify_record or `rtl-ass kb verify` for atomic evidence recording and verification",
            )
        with self._connect() as connection:
            self._require_schema(connection)
            return self._transition_record(
                connection,
                record_id,
                target,
                actor=actor,
                evidence=None,
                required_evidence_kinds=(),
            )

    def add_link(
        self,
        source_record_id: str,
        target_record_id: str,
        relation: LinkRelation,
        *,
        actor: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        validate_identifier(actor, "actor")
        with self._connect() as connection:
            self._require_schema(connection)
            return self._insert_link(
                connection,
                source_record_id,
                target_record_id,
                relation,
                actor=actor,
                metadata=metadata,
            )

    def verify_record(
        self,
        record_id: str,
        evidence_items: Iterable[Mapping[str, Any]],
        *,
        actor: str,
        required_evidence_kinds: Iterable[str] = (),
    ) -> dict[str, Any]:
        validate_identifier(actor, "actor")
        items = tuple(evidence_items)
        requirements = tuple(required_evidence_kinds)
        with self._connect() as connection:
            self._require_schema(connection)
            target = self._get_record(connection, record_id)
            gate = build_verification_gate(
                items,
                content_hash=target["content_hash"],
                required_evidence_kinds=requirements,
                require_current_artifacts=True,
            )
            evidence_records: list[dict[str, Any]] = []
            links: list[dict[str, Any]] = []
            for index, item in enumerate(gate["evidence"]):
                evidence_record = build_tool_evidence_record(target, item)
                stored = self._insert_record(connection, evidence_record, actor=actor)
                evidence_records.append(stored["record"])
                links.append(
                    self._insert_link(
                        connection,
                        stored["record"]["id"],
                        record_id,
                        LinkRelation.EVIDENCE_FOR,
                        actor=actor,
                        metadata={"evidence_index": index, "kind": item["kind"], "input_hash": item["input_hash"]},
                    )
                )
            confirmed_gate = build_verification_gate(
                gate["evidence"],
                content_hash=target["content_hash"],
                required_evidence_kinds=requirements,
                require_current_artifacts=True,
            )
            if confirmed_gate != gate:
                raise RtlAssError("evidence_changed", "verification evidence changed during atomic recording")
            verified = self._transition_record(
                connection,
                record_id,
                RecordStatus.VERIFIED,
                actor=actor,
                evidence=gate,
                required_evidence_kinds=requirements,
            )
            return {
                "schema_version": "1.0",
                "record": verified,
                "gate": gate,
                "evidence_records": evidence_records,
                "links": links,
            }

    def record_observations(
        self,
        record_id: str,
        evidence_items: Iterable[Mapping[str, Any]],
        *,
        actor: str,
        attribution: ObservationAttribution,
    ) -> dict[str, Any]:
        validate_identifier(actor, "actor")
        if not isinstance(attribution, ObservationAttribution):
            raise RtlAssError("invalid_attribution", "observation attribution must use a supported explicit value")
        items = tuple(evidence_items)
        with self._connect() as connection:
            self._require_schema(connection)
            target = self._get_record(connection, record_id)
            if RecordRole(target["role"]) is RecordRole.TOOL_EVIDENCE:
                raise RtlAssError(
                    "invalid_observation_target", "tool evidence cannot be the target of another observation"
                )
            observation = build_observation_set(
                items,
                content_hash=target["content_hash"],
                require_current_artifacts=True,
            )
            if attribution is ObservationAttribution.TARGET and observation["observed_statuses"] != ["fail"]:
                raise RtlAssError(
                    "invalid_failure_attribution",
                    "only an executed fail may be attributed to the target as negative evidence",
                    {"observed_statuses": observation["observed_statuses"]},
                )
            relation = (
                LinkRelation.NEGATIVE_FOR if attribution is ObservationAttribution.TARGET else LinkRelation.EVIDENCE_FOR
            )
            evidence_records: list[dict[str, Any]] = []
            links: list[dict[str, Any]] = []
            for index, item in enumerate(observation["evidence"]):
                stored = self._insert_record(
                    connection,
                    build_tool_evidence_record(target, item),
                    actor=actor,
                )
                evidence_records.append(stored["record"])
                link_metadata = {
                    "observation_index": index,
                    "kind": item["kind"],
                    "status": item["status"],
                    "input_hash": item["input_hash"],
                    "attribution": attribution.value,
                }
                links.append(
                    self._insert_observation_link(
                        connection,
                        stored["record"]["id"],
                        record_id,
                        relation,
                        actor=actor,
                        metadata=link_metadata,
                    )
                )
            confirmed = build_observation_set(
                observation["evidence"],
                content_hash=target["content_hash"],
                require_current_artifacts=True,
            )
            if confirmed != observation:
                raise RtlAssError("evidence_changed", "observation evidence changed during atomic recording")
            return {
                "schema_version": "1.0",
                "record": self._get_record(connection, record_id),
                "observation": observation,
                "attribution": attribution.value,
                "evidence_records": evidence_records,
                "links": links,
            }

    def list_links(self, record_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            self._require_schema(connection)
            self._get_record(connection, record_id)
            rows = connection.execute(
                """
                SELECT id, source_record_id, target_record_id, relation, metadata_json, created_at
                FROM record_links
                WHERE source_record_id = ? OR target_record_id = ?
                ORDER BY id
                """,
                (record_id, record_id),
            ).fetchall()
            return [
                {
                    **{
                        key: row[key]
                        for key in ("id", "source_record_id", "target_record_id", "relation", "created_at")
                    },
                    "metadata": database_json(row["metadata_json"], "record_links.metadata_json"),
                }
                for row in rows
            ]

    def list_audit(self, limit: int = 50) -> list[dict[str, Any]]:
        if limit < 1 or limit > 500:
            raise RtlAssError("invalid_limit", "audit limit must be between 1 and 500", {"limit": limit})
        with self._connect() as connection:
            self._require_schema(connection)
            rows = connection.execute(
                "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["details"] = database_json(item.pop("details_json"), "audit_events.details_json")
                result.append(item)
            return result

    def statistics(self) -> dict[str, Any]:
        with self._connect() as connection:
            self._require_schema(connection)

            def grouped(field: str) -> dict[str, int]:
                rows = connection.execute(
                    f"SELECT {field}, count(*) AS count FROM records GROUP BY {field} ORDER BY {field}"
                ).fetchall()
                return {str(row[field]): int(row["count"]) for row in rows}

            counts = connection.execute(
                """
                SELECT
                    (SELECT count(*) FROM records) AS records,
                    (SELECT count(*) FROM blobs) AS unique_blobs,
                    (SELECT coalesce(sum(byte_count), 0) FROM blobs) AS unique_content_bytes,
                    (SELECT count(*) FROM record_links) AS links,
                    (SELECT count(*) FROM audit_events) AS audit_events
                """
            ).fetchone()
            if counts is None:
                raise AssertionError("aggregate statistics query must return one row")
            audit = verify_audit_chain(connection)
            if not audit["valid"]:
                raise RtlAssError("database_audit_invalid", "knowledge statistics require a valid audit chain", audit)
            return {
                "schema_version": "1.0",
                "records": int(counts["records"]),
                "unique_blobs": int(counts["unique_blobs"]),
                "unique_content_bytes": int(counts["unique_content_bytes"]),
                "links": int(counts["links"]),
                "audit_events": int(counts["audit_events"]),
                "by_namespace": grouped("namespace"),
                "by_role": grouped("role"),
                "by_language": grouped("language"),
                "by_status": grouped("status"),
                "by_license": grouped("license_spdx"),
                "audit_chain": audit,
            }

    def verify_audit_chain(self) -> dict[str, Any]:
        with self._connect() as connection:
            self._require_schema(connection)
            return verify_audit_chain(connection)

    @staticmethod
    def _require_schema(connection: sqlite3.Connection) -> None:
        require_current_schema(connection)
