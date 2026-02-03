from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from rtl_ass.kb import KnowledgeDatabase


class AuditTests(unittest.TestCase):
    def test_audit_rows_cannot_be_updated_or_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.db"
            KnowledgeDatabase(path).initialize(actor="test-suite")
            connection = sqlite3.connect(path)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE audit_events SET actor = 'changed' WHERE id = 1")
            connection.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM audit_events WHERE id = 1")
            connection.close()

    def test_hash_chain_detects_out_of_band_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.db"
            database = KnowledgeDatabase(path)
            database.initialize(actor="test-suite")
            self.assertTrue(database.verify_audit_chain()["valid"])

            connection = sqlite3.connect(path)
            connection.execute("DROP TRIGGER audit_events_no_update")
            connection.execute("UPDATE audit_events SET actor = 'tampered' WHERE id = 1")
            connection.commit()
            connection.close()

            result = database.verify_audit_chain()
            self.assertFalse(result["valid"])
            self.assertEqual(result["reason"], "event_hash_mismatch")

    def test_hash_chain_rejects_nonfinite_json_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.db"
            database = KnowledgeDatabase(path)
            database.initialize(actor="test-suite")
            connection = sqlite3.connect(path)
            connection.execute("DROP TRIGGER audit_events_no_update")
            connection.execute("UPDATE audit_events SET details_json = '{\"value\": NaN}' WHERE id = 1")
            connection.commit()
            connection.close()
            result = database.verify_audit_chain()
            self.assertFalse(result["valid"])
            self.assertEqual(result["reason"], "invalid_details_json")


if __name__ == "__main__":
    unittest.main()
