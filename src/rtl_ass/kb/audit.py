"""Append-only, hash-chained audit primitives."""

from __future__ import annotations

import sqlite3
from typing import Any, Mapping

from rtl_ass.integrity import canonical_json, hash_json, parse_json, utc_now

AUDIT_GENESIS_HASH = "0" * 64


def append_audit(
    connection: sqlite3.Connection,
    *,
    actor: str,
    action: str,
    subject_type: str,
    subject_id: str,
    previous_state: str | None,
    new_state: str | None,
    inputs: Mapping[str, Any],
    outputs: Mapping[str, Any],
    details: Mapping[str, Any],
) -> None:
    occurred_at = utc_now()
    input_hash = hash_json(inputs)
    output_hash = hash_json(outputs)
    details_value = dict(details)
    previous = connection.execute("SELECT event_hash FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
    previous_event_hash = previous["event_hash"] if previous is not None else AUDIT_GENESIS_HASH
    event_payload = {
        "occurred_at": occurred_at,
        "actor": actor,
        "action": action,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "previous_state": previous_state,
        "new_state": new_state,
        "input_hash": input_hash,
        "output_hash": output_hash,
        "details": details_value,
        "previous_event_hash": previous_event_hash,
    }
    event_hash = hash_json(event_payload)
    connection.execute(
        """
        INSERT INTO audit_events(
            occurred_at, actor, action, subject_type, subject_id,
            previous_state, new_state, input_hash, output_hash, details_json,
            previous_event_hash, event_hash
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            occurred_at,
            actor,
            action,
            subject_type,
            subject_id,
            previous_state,
            new_state,
            input_hash,
            output_hash,
            canonical_json(details_value),
            previous_event_hash,
            event_hash,
        ),
    )


def verify_audit_chain(connection: sqlite3.Connection) -> dict[str, Any]:
    rows = connection.execute("SELECT * FROM audit_events ORDER BY id ASC").fetchall()
    previous_hash = AUDIT_GENESIS_HASH
    for row in rows:
        if row["previous_event_hash"] != previous_hash:
            return _invalid_result(rows, row["id"], "previous_event_hash_mismatch")
        try:
            details = parse_json(row["details_json"])
        except (TypeError, ValueError):
            return _invalid_result(rows, row["id"], "invalid_details_json")
        if not isinstance(details, dict):
            return _invalid_result(rows, row["id"], "invalid_details_type")
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
            "previous_event_hash": row["previous_event_hash"],
        }
        expected_hash = hash_json(payload)
        if row["event_hash"] != expected_hash:
            return _invalid_result(rows, row["id"], "event_hash_mismatch")
        previous_hash = row["event_hash"]
    return {
        "valid": True,
        "event_count": len(rows),
        "head_event_hash": previous_hash,
    }


def _invalid_result(rows: list[sqlite3.Row], event_id: int, reason: str) -> dict[str, Any]:
    return {
        "valid": False,
        "event_count": len(rows),
        "failed_event_id": event_id,
        "reason": reason,
    }
