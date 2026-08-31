from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rtl_ass.cli import main
from rtl_ass.evidence import run_iverilog_simulation, run_verilator_lint
from rtl_ass.kb.schema import SCHEMA_VERSION


class CliTests(unittest.TestCase):
    def test_operating_system_failure_is_a_structured_error(self) -> None:
        error = io.StringIO()
        with mock.patch("rtl_ass.cli.discover_tools", side_effect=PermissionError(13, "denied")):
            with contextlib.redirect_stderr(error):
                status = main(["doctor"])
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(error.getvalue())["error"]["code"], "io_error")

    @unittest.skipUnless(shutil.which("yosys"), "Yosys is unavailable")
    def test_formal_and_equivalence_cli_emit_machine_readable_evidence(self) -> None:
        fixtures = Path(__file__).parent / "fixtures"
        with tempfile.TemporaryDirectory() as directory:
            formal_output = io.StringIO()
            with contextlib.redirect_stdout(formal_output):
                formal_status = main(
                    [
                        "verify",
                        "formal",
                        "--source",
                        str(fixtures / "formal_pass.sv"),
                        "--top",
                        "formal_pass",
                        "--depth",
                        "3",
                        "--artifact-dir",
                        directory,
                    ]
                )
            equivalence_output = io.StringIO()
            with contextlib.redirect_stdout(equivalence_output):
                equivalence_status = main(
                    [
                        "verify",
                        "equiv",
                        "--reference-source",
                        str(fixtures / "equiv_reference.sv"),
                        "--implementation-source",
                        str(fixtures / "equiv_implementation.sv"),
                        "--reference-top",
                        "equiv_reference",
                        "--implementation-top",
                        "equiv_implementation",
                        "--artifact-dir",
                        directory,
                    ]
                )
        self.assertEqual(formal_status, 0)
        self.assertEqual(equivalence_status, 0)
        self.assertEqual(json.loads(formal_output.getvalue())["status"], "pass")
        self.assertEqual(json.loads(equivalence_output.getvalue())["status"], "pass")

    def test_kb_init_emits_json_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = main(["kb", "init", "--db", str(Path(directory) / "index.db"), "--actor", "test-suite"])
            self.assertEqual(status, 0)
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["created"])
            self.assertEqual(payload["schema_version"], SCHEMA_VERSION)

    def test_uninitialized_database_is_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                status = main(
                    [
                        "kb",
                        "search",
                        "counter",
                        "--db",
                        str(Path(directory) / "missing.db"),
                        "--namespace",
                        "project:test",
                    ]
                )
            self.assertEqual(status, 2)
            payload = json.loads(error.getvalue())
            self.assertEqual(payload["error"]["code"], "database_not_initialized")

    @unittest.skipUnless(shutil.which("verilator"), "Verilator is unavailable")
    def test_kb_observe_retains_real_failure_with_explicit_attribution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            database = temporary / "index.db"
            source = temporary / "broken.sv"
            source.write_text("module broken(input logic clk); this_is_not_valid endmodule\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["kb", "init", "--db", str(database), "--actor", "test-suite"]), 0)
            ingest_output = io.StringIO()
            with contextlib.redirect_stdout(ingest_output):
                status = main(
                    [
                        "kb",
                        "ingest",
                        str(source),
                        "--db",
                        str(database),
                        "--namespace",
                        "project:observe",
                        "--initial-status",
                        "candidate",
                        "--actor",
                        "test-suite",
                    ]
                )
            self.assertEqual(status, 0)
            record_id = json.loads(ingest_output.getvalue())["records"][0]["id"]
            evidence = run_verilator_lint([source], top="broken", artifact_root=temporary / "artifacts")
            self.assertEqual(evidence["status"], "fail")
            observe_output = io.StringIO()
            with contextlib.redirect_stdout(observe_output):
                observe_status = main(
                    [
                        "kb",
                        "observe",
                        record_id,
                        "--db",
                        str(database),
                        "--actor",
                        "reviewer",
                        "--attribution",
                        "target",
                        "--evidence-json",
                        evidence["evidence_file"],
                    ]
                )
            self.assertEqual(observe_status, 0, observe_output.getvalue())
            result = json.loads(observe_output.getvalue())
            self.assertEqual(result["record"]["status"], "candidate")
            self.assertEqual(result["links"][0]["relation"], "negative-for")

    @unittest.skipUnless(
        shutil.which("iverilog") and shutil.which("vvp") and shutil.which("verilator"),
        "Icarus Verilog or Verilator is unavailable",
    )
    def test_configured_multitool_gate_verifies_and_lists_evidence_links(self) -> None:
        root = Path(__file__).resolve().parents[1]
        fixtures = root / "tests" / "fixtures"
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            database = temporary / "index.db"
            config = temporary / "rtl-ass.toml"
            config.write_text(
                "\n".join(
                    [
                        "schema_version = 1",
                        "[knowledge]",
                        f'database = "{database.as_posix()}"',
                        'default_namespace = "project:cli"',
                        "[verification.gates.rtl-design]",
                        'required_kinds = ["lint", "simulation"]',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            init_output = io.StringIO()
            with contextlib.redirect_stdout(init_output):
                init_status = main(["--config", str(config), "kb", "init", "--actor", "test-suite"])
            self.assertEqual(init_status, 0, init_output.getvalue())
            ingest_output = io.StringIO()
            with contextlib.redirect_stdout(ingest_output):
                status = main(
                    [
                        "--config",
                        str(config),
                        "kb",
                        "ingest",
                        str(fixtures / "counter.sv"),
                        "--initial-status",
                        "candidate",
                        "--actor",
                        "test-suite",
                    ]
                )
            self.assertEqual(status, 0)
            record_id = json.loads(ingest_output.getvalue())["records"][0]["id"]
            evidence = [
                run_verilator_lint([fixtures / "counter.sv"], top="counter", artifact_root=temporary / "artifacts"),
                run_iverilog_simulation(
                    [fixtures / "counter.sv", fixtures / "counter_tb.sv"],
                    top="counter_tb",
                    artifact_root=temporary / "artifacts",
                ),
            ]
            evidence_paths: list[Path] = []
            for index, item in enumerate(evidence):
                path = temporary / f"evidence-{index}.json"
                path.write_text(json.dumps(item), encoding="utf-8")
                evidence_paths.append(path)
            verify_output = io.StringIO()
            verify_arguments = ["--config", str(config), "kb", "verify", record_id, "--actor", "test-suite"]
            for path in evidence_paths:
                verify_arguments.extend(["--evidence-json", str(path)])
            with contextlib.redirect_stdout(verify_output):
                verify_status = main(verify_arguments)
            self.assertEqual(verify_status, 0, verify_output.getvalue())
            verify_result = json.loads(verify_output.getvalue())
            self.assertEqual(verify_result["record"]["status"], "verified")
            self.assertEqual(len(verify_result["evidence_records"]), 2)
            links_output = io.StringIO()
            with contextlib.redirect_stdout(links_output):
                links_status = main(["--config", str(config), "kb", "links", record_id])
            self.assertEqual(links_status, 0)
            self.assertEqual(json.loads(links_output.getvalue())["count"], 2)


if __name__ == "__main__":
    unittest.main()
