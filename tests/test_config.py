from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from rtl_ass.cli import main
from rtl_ass.config import load_settings
from rtl_ass.errors import RtlAssError
from rtl_ass.kb.database import KnowledgeDatabase
from rtl_ass.kb.models import RecordRole

ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def test_example_configuration_is_fully_consumed(self) -> None:
        settings = load_settings(ROOT / "config" / "rtl-ass.example.toml")
        self.assertEqual(settings.default_namespace, "project:default")
        self.assertEqual(settings.search_limit, 5)
        self.assertFalse(settings.follow_symlinks)
        self.assertEqual(settings.required_evidence_kinds(RecordRole.RTL_DESIGN), ("lint", "simulation"))
        self.assertEqual(settings.required_evidence_kinds(RecordRole.TESTBENCH), ("simulation",))

    def test_unknown_configuration_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.toml"
            path.write_text("schema_version = 1\n[knowledge.policy]\nautomatic_promotion = true\n", encoding="utf-8")
            with self.assertRaises(RtlAssError) as caught:
                load_settings(path)
        self.assertEqual(caught.exception.code, "unknown_config_key")

    def test_cli_uses_configured_database_and_ingest_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "configured.db"
            config = root / "rtl-ass.toml"
            config.write_text(
                "\n".join(
                    [
                        "schema_version = 1",
                        "[knowledge]",
                        f'database = "{database.as_posix()}"',
                        'default_namespace = "project:configured"',
                        "search_limit = 3",
                        "[project]",
                        "max_source_bytes = 1048576",
                        "follow_symlinks = false",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                init_status = main(["--config", str(config), "kb", "init", "--actor", "test-suite"])
            self.assertEqual(init_status, 0, output.getvalue())
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                ingest_status = main(
                    ["--config", str(config), "kb", "ingest", str(ROOT / "tests" / "fixtures" / "counter.sv")]
                )
            self.assertEqual(ingest_status, 0, output.getvalue())
            results = KnowledgeDatabase(database).search("counter", namespaces=["project:configured"])
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["namespace"], "project:configured")

    def test_invalid_config_is_a_structured_cli_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.toml"
            path.write_text("schema_version = 2\n", encoding="utf-8")
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                status = main(["--config", str(path), "doctor"])
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(error.getvalue())["error"]["code"], "invalid_config")

    def test_unknown_evidence_kind_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid-kind.toml"
            path.write_text(
                'schema_version = 1\n[verification.gates.rtl-design]\nrequired_kinds = ["simulation", "magic"]\n',
                encoding="utf-8",
            )
            with self.assertRaises(RtlAssError) as caught:
                load_settings(path)
        self.assertEqual(caught.exception.code, "invalid_evidence_kind")

    def test_search_limit_cannot_exceed_database_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid-limit.toml"
            path.write_text("schema_version = 1\n[knowledge]\nsearch_limit = 51\n", encoding="utf-8")
            with self.assertRaises(RtlAssError) as caught:
                load_settings(path)
        self.assertEqual(caught.exception.code, "invalid_config")


if __name__ == "__main__":
    unittest.main()
