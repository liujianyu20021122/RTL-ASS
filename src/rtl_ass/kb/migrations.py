"""Explicit, transaction-owned knowledge database migrations."""

from __future__ import annotations

import sqlite3

from rtl_ass.errors import RtlAssError
from rtl_ass.integrity import hash_json, parse_json
from rtl_ass.kb.audit import AUDIT_GENESIS_HASH, append_audit
from rtl_ass.kb.schema import SCHEMA_VERSION, create_audit_triggers

_V1_AUDIT_COLUMNS = {
    "id",
    "occurred_at",
    "actor",
    "action",
    "subject_type",
    "subject_id",
    "previous_state",
    "new_state",
    "input_hash",
    "output_hash",
    "details_json",
}
_REQUIRED_V1_TABLES = {"metadata", "blobs", "records", "records_fts", "record_links", "audit_events"}


def migrate_v1_to_v2(connection: sqlite3.Connection, *, actor: str) -> None:
    _require_v1_structure(connection)
    connection.execute("DROP TRIGGER IF EXISTS audit_events_no_update")
    connection.execute("DROP TRIGGER IF EXISTS audit_events_no_delete")
    connection.execute(
        """
        CREATE TABLE audit_events_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TEXT NOT NULL,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            subject_type TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            previous_state TEXT,
            new_state TEXT,
            input_hash TEXT NOT NULL,
            output_hash TEXT NOT NULL,
            details_json TEXT NOT NULL,
            previous_event_hash TEXT NOT NULL,
            event_hash TEXT NOT NULL UNIQUE
        )
        """
    )
    rows = connection.execute("SELECT * FROM audit_events ORDER BY id").fetchall()
    _backfill_audit_chain(connection, rows)
    connection.execute("DROP TABLE audit_events")
    connection.execute("ALTER TABLE audit_events_v2 RENAME TO audit_events")
    connection.execute("UPDATE metadata SET value = ? WHERE key = 'schema_version'", (str(SCHEMA_VERSION),))
    create_audit_triggers(connection)
    append_audit(
        connection,
        actor=actor,
        action="database.migrate",
        subject_type="database",
        subject_id="schema",
        previous_state="1",
        new_state=str(SCHEMA_VERSION),
        inputs={"from_version": 1, "to_version": SCHEMA_VERSION},
        outputs={"backfilled_event_count": len(rows), "schema_version": SCHEMA_VERSION},
        details={"migration": "v1-to-v2-audit-hash-chain"},
    )


def _require_v1_structure(connection: sqlite3.Connection) -> None:
    tables = {
        row["name"]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')").fetchall()
    }
    missing_tables = sorted(_REQUIRED_V1_TABLES.difference(tables))
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(audit_events)").fetchall()}
    if missing_tables or columns != _V1_AUDIT_COLUMNS:
        raise RtlAssError(
            "migration_precondition_failed",
            "schema v1 structure does not match the verified migration precondition",
            {"missing_tables": missing_tables, "audit_columns": sorted(columns)},
        )


def _backfill_audit_chain(connection: sqlite3.Connection, rows: list[sqlite3.Row]) -> None:
    previous_hash = AUDIT_GENESIS_HASH
    for row in rows:
        try:
            details = parse_json(row["details_json"])
        except (TypeError, ValueError) as exc:
            raise _invalid_audit(row["id"], "details_json is not valid JSON") from exc
        if not isinstance(details, dict):
            raise _invalid_audit(row["id"], "details_json is not an object")
        payload = {
            "occurred_at": row["occurred_at"],
            "actor": row["actor"],
            "action": row["action"],
            "subject_type": row["subject_type"],
            "subject_id": row["subject_id"],
            "previous_state": row["previous_state"],
            "new_state": row["new_state"],
            "input_hash": row["input_hash"],
            "output_hash": row["output_hash"],
            "details": details,
            "previous_event_hash": previous_hash,
        }
        event_hash = hash_json(payload)
        connection.execute(
            """
            INSERT INTO audit_events_v2(
                id, occurred_at, actor, action, subject_type, subject_id,
                previous_state, new_state, input_hash, output_hash, details_json,
                previous_event_hash, event_hash
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["occurred_at"],
                row["actor"],
                row["action"],
                row["subject_type"],
                row["subject_id"],
                row["previous_state"],
                row["new_state"],
                row["input_hash"],
                row["output_hash"],
                row["details_json"],
                previous_hash,
                event_hash,
            ),
        )
        previous_hash = event_hash


def _invalid_audit(event_id: int, reason: str) -> RtlAssError:
    return RtlAssError(
        "migration_invalid_audit",
        "schema v1 contains an invalid audit event",
        {"event_id": event_id, "reason": reason},
    )
