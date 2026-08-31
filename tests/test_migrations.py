from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rtl_ass.cli import main
from rtl_ass.errors import RtlAssError
from rtl_ass.integrity import canonical_json, hash_json
from rtl_ass.kb.database import KnowledgeDatabase
from rtl_ass.kb.schema import AUDIT_TRIGGER_SQL, SCHEMA_SQL


class MigrationTests(unittest.TestCase):
    def test_v1_to_v2_preserves_events_and_builds_valid_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.db"
            self._create_v1_database(path)
            database = KnowledgeDatabase(path)
            result = database.migrate(actor="migration-test")
            self.assertTrue(result["migrated"])
            self.assertEqual((result["from_version"], result["to_version"]), (1, 2))
            self.assertTrue(result["audit_chain"]["valid"])
            events = database.list_audit()
            self.assertEqual([event["action"] for event in events], ["database.migrate", "database.initialize"])
            connection = sqlite3.connect(path)
            columns = {row[1]: row for row in connection.execute("PRAGMA table_info(audit_events)")}
            self.assertEqual(columns["previous_event_hash"][3], 1)
            self.assertEqual(columns["event_hash"][3], 1)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE audit_events SET actor = 'tampered' WHERE id = 1")
            connection.close()

    def test_current_schema_migration_is_idempotent_and_does_not_append_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.db"
            database = KnowledgeDatabase(path)
            database.initialize(actor="test-suite")
            before = database.list_audit()
            result = database.migrate(actor="migration-test")
            self.assertFalse(result["migrated"])
            self.assertEqual(database.list_audit(), before)

    def test_cli_runs_only_the_explicit_v1_to_v2_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.db"
            self._create_v1_database(path)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = main(["kb", "migrate", "--db", str(path), "--actor", "migration-test"])
            self.assertEqual(status, 0)
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["migrated"])
            self.assertEqual(payload["from_version"], 1)
            self.assertEqual(payload["to_version"], 2)
            self.assertTrue(payload["audit_chain"]["valid"])

    def test_unknown_schema_has_no_guessed_migration_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.db"
            self._create_v1_database(path)
            connection = sqlite3.connect(path)
            connection.execute("UPDATE metadata SET value = '0' WHERE key = 'schema_version'")
            connection.commit()
            connection.close()
            with self.assertRaises(RtlAssError) as caught:
                KnowledgeDatabase(path).migrate(actor="migration-test")
            self.assertEqual(caught.exception.code, "unsupported_migration")

    def test_init_rejects_v1_without_mutating_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.db"
            self._create_v1_database(path)
            connection = sqlite3.connect(path)
            before = connection.execute(
                "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
            ).fetchall()
            connection.close()
            with self.assertRaises(RtlAssError) as caught:
                KnowledgeDatabase(path).initialize(actor="test-suite")
            self.assertEqual(caught.exception.code, "schema_version_mismatch")
            connection = sqlite3.connect(path)
            after = connection.execute(
                "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
            ).fetchall()
            connection.close()
            self.assertEqual(after, before)

    def test_init_rejects_unknown_nonempty_database_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.db"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE unrelated(value TEXT)")
            connection.commit()
            connection.close()
            with self.assertRaises(RtlAssError) as caught:
                KnowledgeDatabase(path).initialize(actor="test-suite")
            self.assertEqual(caught.exception.code, "database_not_empty")
            connection = sqlite3.connect(path)
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            connection.close()
            self.assertEqual(tables, [("unrelated",)])

    def test_unknown_v1_audit_column_is_rejected_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.db"
            self._create_v1_database(path)
            connection = sqlite3.connect(path)
            connection.execute("ALTER TABLE audit_events ADD COLUMN undocumented TEXT")
            connection.commit()
            connection.close()
            with self.assertRaises(RtlAssError) as caught:
                KnowledgeDatabase(path).migrate(actor="migration-test")
            self.assertEqual(caught.exception.code, "migration_precondition_failed")
            connection = sqlite3.connect(path)
            version = connection.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()[0]
            columns = {row[1] for row in connection.execute("PRAGMA table_info(audit_events)")}
            connection.close()
            self.assertEqual(version, "1")
            self.assertIn("undocumented", columns)

    def test_failed_in_transaction_chain_check_rolls_back_every_schema_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.db"
            self._create_v1_database(path)
            invalid = {"valid": False, "event_count": 2, "reason": "test-forced-failure"}
            with mock.patch("rtl_ass.kb.database.verify_audit_chain", return_value=invalid):
                with self.assertRaises(RtlAssError) as caught:
                    KnowledgeDatabase(path).migrate(actor="migration-test")
            self.assertEqual(caught.exception.code, "migration_audit_invalid")
            connection = sqlite3.connect(path)
            version = connection.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()[0]
            columns = {row[1] for row in connection.execute("PRAGMA table_info(audit_events)")}
            actions = connection.execute("SELECT action FROM audit_events ORDER BY id").fetchall()
            connection.close()
            self.assertEqual(version, "1")
            self.assertNotIn("event_hash", columns)
            self.assertEqual(actions, [("database.initialize",)])

    def test_invalid_v1_audit_rolls_back_schema_and_restores_triggers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.db"
            self._create_v1_database(path, details_json="not-json")
            with self.assertRaises(RtlAssError) as caught:
                KnowledgeDatabase(path).migrate(actor="migration-test")
            self.assertEqual(caught.exception.code, "migration_invalid_audit")
            connection = sqlite3.connect(path)
            version = connection.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()[0]
            columns = {row[1] for row in connection.execute("PRAGMA table_info(audit_events)")}
            self.assertEqual(version, "1")
            self.assertNotIn("event_hash", columns)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE audit_events SET actor = 'tampered' WHERE id = 1")
            connection.close()

    def test_nonfinite_v1_audit_json_is_a_structured_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.db"
            self._create_v1_database(path, details_json='{"value": NaN}')
            with self.assertRaises(RtlAssError) as caught:
                KnowledgeDatabase(path).migrate(actor="migration-test")
            self.assertEqual(caught.exception.code, "migration_invalid_audit")
            connection = sqlite3.connect(path)
            version = connection.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()[0]
            columns = {row[1] for row in connection.execute("PRAGMA table_info(audit_events)")}
            connection.close()
            self.assertEqual(version, "1")
            self.assertNotIn("event_hash", columns)

    @staticmethod
    def _create_v1_database(path: Path, *, details_json: str = "{}") -> None:
        connection = sqlite3.connect(path)
        connection.executescript(SCHEMA_SQL)
        connection.execute("DROP TABLE audit_events")
        connection.execute(
            """
            CREATE TABLE audit_events (
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
                details_json TEXT NOT NULL
            )
            """
        )
        for statement in AUDIT_TRIGGER_SQL:
            connection.execute(statement)
        connection.execute("INSERT INTO metadata(key, value) VALUES('schema_version', '1')")
        connection.execute(
            """
            INSERT INTO audit_events(
                occurred_at, actor, action, subject_type, subject_id, previous_state,
                new_state, input_hash, output_hash, details_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "2026-08-31T00:00:00+00:00",
                "test-suite",
                "database.initialize",
                "database",
                "index.db",
                None,
                "1",
                hash_json({"path_name": "index.db"}),
                hash_json({"schema_version": 1}),
                details_json if details_json != "{}" else canonical_json({"schema_version": 1}),
            ),
        )
        connection.commit()
        connection.close()


if __name__ == "__main__":
    unittest.main()
