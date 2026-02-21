from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from rtl_ass.cli import main
from rtl_ass.errors import RtlAssError
from rtl_ass.kb.database import KnowledgeDatabase
from rtl_ass.kb.retrieval import build_retrieval_receipt, validate_retrieval_receipt, write_retrieval_receipt

ROOT = Path(__file__).resolve().parents[1]


class RetrievalReceiptTests(unittest.TestCase):
    def _database(self, root: Path) -> KnowledgeDatabase:
        database = KnowledgeDatabase(root / "index.db")
        database.initialize(actor="test-suite")
        database.import_pack(
            ROOT / "library" / "starter" / "pack.json",
            namespace="builtin:starter",
            actor="test-suite",
        )
        return database

    def test_receipt_binds_query_results_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = self._database(Path(temporary))
            results = database.search("ready", namespaces=["builtin:starter"], limit=3)
            receipt = build_retrieval_receipt(
                results,
                actor="codex",
                query="ready",
                namespaces=["builtin:starter"],
                limit=3,
                role=None,
                status=None,
                match_mode="all",
            )
        validated = validate_retrieval_receipt(receipt)
        self.assertEqual(validated["result_count"], len(results))
        self.assertLessEqual(validated["result_count"], 3)
        self.assertEqual([item["index"] for item in validated["results"]], list(range(len(results))))

        tampered = json.loads(json.dumps(receipt))
        tampered["results"][0]["summary"] += " changed"
        with self.assertRaises(RtlAssError) as caught:
            validate_retrieval_receipt(tampered)
        self.assertEqual(caught.exception.code, "retrieval_hash_mismatch")

    def test_match_mode_is_explicit_and_any_recovers_bounded_partial_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = self._database(Path(temporary))
            query = "ready deliberately-absent-token"
            self.assertEqual(
                database.search(query, namespaces=["builtin:starter"], limit=3, match_mode="all"),
                [],
            )
            results = database.search(query, namespaces=["builtin:starter"], limit=3, match_mode="any")
            receipt = build_retrieval_receipt(
                results,
                actor="codex",
                query=query,
                namespaces=["builtin:starter"],
                limit=3,
                role=None,
                status=None,
                match_mode="any",
            )

        self.assertGreater(len(results), 0)
        self.assertEqual(receipt["filters"]["match_mode"], "any")
        with self.assertRaises(RtlAssError) as caught:
            database.search("ready", namespaces=["builtin:starter"], match_mode="fallback")
        self.assertEqual(caught.exception.code, "invalid_match_mode")

    def test_receipt_output_is_atomic_and_rejects_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = self._database(root)
            receipt = build_retrieval_receipt(
                database.search("sampling", namespaces=["builtin:starter"], limit=1),
                actor="codex",
                query="sampling",
                namespaces=["builtin:starter"],
                limit=1,
                role=None,
                status=None,
                match_mode="all",
            )
            destination = root / "receipt.json"
            write_retrieval_receipt(receipt, destination)
            self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), receipt)
            target = root / "target.json"
            target.write_text("{}\n", encoding="utf-8")
            link = root / "link.json"
            link.symlink_to(target)
            with self.assertRaises(RtlAssError) as caught:
                write_retrieval_receipt(receipt, link)
            self.assertEqual(caught.exception.code, "invalid_retrieval_output")

    def test_cli_writes_the_exact_machine_readable_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = self._database(root)
            output_path = root / "retrieval.json"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                status = main(
                    [
                        "kb",
                        "search",
                        "ready",
                        "--db",
                        str(database.path),
                        "--namespace",
                        "builtin:starter",
                        "--limit",
                        "3",
                        "--actor",
                        "codex",
                        "--output",
                        str(output_path),
                    ]
                )
            printed = json.loads(stdout.getvalue())
            stored = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(status, 0)
        self.assertEqual(printed, stored)
        self.assertEqual(validate_retrieval_receipt(stored), stored)


if __name__ == "__main__":
    unittest.main()
