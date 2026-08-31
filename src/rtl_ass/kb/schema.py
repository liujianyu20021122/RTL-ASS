"""Versioned SQLite schema primitives for the knowledge store."""

from __future__ import annotations

import sqlite3

from rtl_ass.errors import RtlAssError

SCHEMA_VERSION = 2

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS blobs (
    content_hash TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    byte_count INTEGER NOT NULL CHECK (byte_count >= 0),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY,
    namespace TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL,
    language TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    content_hash TEXT NOT NULL REFERENCES blobs(content_hash),
    source_uri TEXT NOT NULL,
    source_revision TEXT NOT NULL,
    source_path TEXT NOT NULL,
    license_spdx TEXT NOT NULL,
    license_status TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    verification_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS records_namespace_idx ON records(namespace);
CREATE INDEX IF NOT EXISTS records_hash_idx ON records(content_hash);
CREATE INDEX IF NOT EXISTS records_role_status_idx ON records(role, status);

CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
    record_id UNINDEXED,
    title,
    summary,
    content,
    tokenize = 'unicode61'
);

CREATE TABLE IF NOT EXISTS record_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_record_id TEXT NOT NULL REFERENCES records(id),
    target_record_id TEXT NOT NULL REFERENCES records(id),
    relation TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(source_record_id, target_record_id, relation)
);

CREATE TABLE IF NOT EXISTS audit_events (
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
);
"""

AUDIT_TRIGGER_SQL = (
    """
    CREATE TRIGGER IF NOT EXISTS audit_events_no_update
    BEFORE UPDATE ON audit_events
    BEGIN
        SELECT RAISE(ABORT, 'audit events are append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
    BEFORE DELETE ON audit_events
    BEGIN
        SELECT RAISE(ABORT, 'audit events are append-only');
    END
    """,
)


def create_audit_triggers(connection: sqlite3.Connection) -> None:
    for statement in AUDIT_TRIGGER_SQL:
        connection.execute(statement)


def read_schema_version(connection: sqlite3.Connection) -> int:
    table = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'metadata'").fetchone()
    if table is None:
        raise RtlAssError("database_not_initialized", "run `rtl-ass kb init` before using the knowledge database")
    row = connection.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()
    if row is None:
        raise RtlAssError("schema_version_missing", "knowledge database does not declare a schema version")
    try:
        return int(row["value"])
    except (TypeError, ValueError) as exc:
        raise RtlAssError("schema_version_invalid", "knowledge database schema version is not an integer") from exc


def require_current_schema(connection: sqlite3.Connection) -> None:
    version = read_schema_version(connection)
    if version != SCHEMA_VERSION:
        raise RtlAssError(
            "schema_version_mismatch",
            "knowledge database schema is unsupported; run `rtl-ass kb migrate` when a verified path exists",
            {"found": version, "expected": SCHEMA_VERSION},
        )
