from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rtl_ass.errors import RtlAssError
from rtl_ass.evidence import (
    EquivalenceInputBundle,
    FormalInputBundle,
    SourceBundle,
    run_iverilog_simulation,
    run_opensta,
    run_verilator_lint,
    run_yosys_equivalence,
    run_yosys_formal,
    run_yosys_synthesis,
)

FIXTURES = Path(__file__).parent / "fixtures"
STA_FIXTURES = Path(__file__).parent / "sta_fixtures"


class EvidenceTests(unittest.TestCase):
    def test_source_bundle_hash_is_ordered_and_content_bound(self) -> None:
        design = FIXTURES / "counter.sv"
        testbench = FIXTURES / "counter_tb.sv"
        first = SourceBundle.create([design, testbench], "counter_tb")
        second = SourceBundle.create([testbench, design], "counter_tb")
        self.assertNotEqual(first.input_hash, second.input_hash)
        self.assertEqual(first.source_hashes[0]["path"], design.as_posix())
        self.assertEqual(first.source_hashes[0]["index"], 0)

    def test_formal_and_equivalence_hashes_bind_proof_parameters_and_roles(self) -> None:
        formal_short = FormalInputBundle.create(
            [FIXTURES / "formal_pass.sv"], top="formal_pass", depth=4, initialization="defined"
        )
        formal_deep = FormalInputBundle.create(
            [FIXTURES / "formal_pass.sv"], top="formal_pass", depth=5, initialization="defined"
        )
        self.assertNotEqual(formal_short.input_hash, formal_deep.input_hash)
        forward = EquivalenceInputBundle.create(
            [FIXTURES / "equiv_reference.sv"],
            [FIXTURES / "equiv_implementation.sv"],
            reference_top="equiv_reference",
            implementation_top="equiv_implementation",
            depth=1,
        )
        reverse = EquivalenceInputBundle.create(
            [FIXTURES / "equiv_implementation.sv"],
            [FIXTURES / "equiv_reference.sv"],
            reference_top="equiv_implementation",
            implementation_top="equiv_reference",
            depth=1,
        )
        undefined = EquivalenceInputBundle.create(
            [FIXTURES / "equiv_reference.sv"],
            [FIXTURES / "equiv_implementation.sv"],
            reference_top="equiv_reference",
            implementation_top="equiv_implementation",
            depth=1,
            input_domain="undefined",
        )
        self.assertNotEqual(forward.input_hash, reverse.input_hash)
        self.assertNotEqual(forward.input_hash, undefined.input_hash)
        self.assertEqual([item["index"] for item in forward.subject_hashes], [0, 1])

    def test_formal_rejects_unbounded_or_boolean_depth(self) -> None:
        for depth in (0, 1001, True):
            with self.subTest(depth=depth), self.assertRaises(RtlAssError) as caught:
                FormalInputBundle.create(
                    [FIXTURES / "formal_pass.sv"],
                    top="formal_pass",
                    depth=depth,
                    initialization="defined",
                )
            self.assertEqual(caught.exception.code, "invalid_formal_depth")

        with tempfile.TemporaryDirectory() as directory, self.assertRaises(RtlAssError) as caught:
            run_yosys_formal(
                [FIXTURES / "formal_pass.sv"],
                top="formal_pass",
                depth=2,
                initialization="defined",
                artifact_root=directory,
                timeout_seconds=True,
            )
        self.assertEqual(caught.exception.code, "invalid_timeout")

    @unittest.skipUnless(shutil.which("iverilog") and shutil.which("vvp"), "Icarus Verilog is unavailable")
    def test_iverilog_simulation_emits_real_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = run_iverilog_simulation(
                [FIXTURES / "counter.sv", FIXTURES / "counter_tb.sv"],
                top="counter_tb",
                artifact_root=directory,
            )
            self.assertEqual(evidence["status"], "pass")
            self.assertEqual(evidence["summary"]["run_returncode"], 0)
            self.assertTrue(Path(evidence["evidence_file"]).is_file())
            self.assertEqual(len(evidence["subject_hashes"]), 2)
            self.assertEqual(len(evidence["commands"]), 2)

    @unittest.skipUnless(shutil.which("verilator"), "Verilator is unavailable")
    def test_verilator_lint_emits_real_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = run_verilator_lint(
                [FIXTURES / "counter.sv"],
                top="counter",
                artifact_root=directory,
            )
            self.assertEqual(evidence["status"], "pass")
            self.assertEqual(evidence["summary"]["returncode"], 0)
            self.assertTrue(Path(evidence["evidence_file"]).is_file())

    @unittest.skipUnless(shutil.which("yosys"), "Yosys is unavailable")
    def test_yosys_synthesis_emits_netlist_and_statistics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = run_yosys_synthesis(
                [FIXTURES / "counter.sv"],
                top="counter",
                artifact_root=directory,
            )
            self.assertEqual(evidence["status"], "pass", evidence["summary"])
            self.assertEqual(evidence["summary"]["returncode"], 0)
            self.assertIn("statistics", evidence["summary"])
            artifact_names = {Path(path).name for path in evidence["artifacts"]}
            self.assertIn("netlist.json", artifact_names)
            self.assertIn("stats.json", artifact_names)
            script_path = next(Path(path) for path in evidence["artifacts"] if Path(path).name == "synthesis.ys")
            script = script_path.read_text(encoding="utf-8")
            self.assertIn("tee -o stats.json stat -json", script)
            self.assertIn("write_json netlist.json", script)

    @unittest.skipUnless(shutil.which("yosys"), "Yosys is unavailable")
    def test_yosys_formal_distinguishes_proof_and_counterexample(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            passing = run_yosys_formal(
                [FIXTURES / "formal_pass.sv"],
                top="formal_pass",
                depth=4,
                initialization="defined",
                artifact_root=directory,
            )
            failing = run_yosys_formal(
                [FIXTURES / "formal_fail.sv"],
                top="formal_fail",
                depth=4,
                initialization="defined",
                artifact_root=directory,
            )
            formal_script = next(Path(path) for path in passing["artifacts"] if Path(path).name == "formal.ys")
            script_text = formal_script.read_text(encoding="utf-8")
        self.assertEqual(passing["status"], "pass", passing["summary"])
        self.assertTrue(passing["summary"]["proof_passed"])
        self.assertEqual(passing["summary"]["mode"], "bounded")
        self.assertEqual(passing["summary"]["depth"], 4)
        self.assertTrue(passing["summary"]["defined_inputs"])
        self.assertEqual(failing["status"], "fail", failing["summary"])
        self.assertFalse(failing["summary"]["proof_passed"])
        self.assertIn("counterexample.vcd", {Path(path).name for path in failing["artifacts"]})
        self.assertIn("select -assert-min 1", script_text)
        self.assertIn("-set-assumes -set-def-inputs", script_text)
        self.assertNotIn("unbounded", passing["claim_scope"])

    @unittest.skipUnless(shutil.which("yosys"), "Yosys is unavailable")
    def test_yosys_formal_blocks_an_empty_proof_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = run_yosys_formal(
                [FIXTURES / "counter.sv"],
                top="counter",
                depth=2,
                initialization="zero",
                artifact_root=directory,
            )
        self.assertEqual(evidence["status"], "blocked", evidence["summary"])
        self.assertIsNone(evidence["summary"]["proof_passed"])

    @unittest.skipUnless(shutil.which("yosys"), "Yosys is unavailable")
    def test_yosys_formal_blocks_if_an_input_changes_during_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "mutable.sv"
            source.write_text((FIXTURES / "formal_pass.sv").read_text(encoding="utf-8"), encoding="utf-8")

            def mutate_input(_command: object, current_run: Path, _timeout: object) -> tuple[int, str, str, bool]:
                source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
                (current_run / "yosys.log").write_text("mocked completed run\n", encoding="utf-8")
                return 0, "", "", False

            with mock.patch("rtl_ass.evidence_yosys._run_yosys", side_effect=mutate_input):
                evidence = run_yosys_formal(
                    [source],
                    top="formal_pass",
                    depth=2,
                    initialization="defined",
                    artifact_root=directory,
                )
        self.assertEqual(evidence["status"], "blocked")
        self.assertTrue(evidence["summary"]["input_changed_during_run"])
        self.assertIsNone(evidence["summary"]["proof_passed"])

    @unittest.skipUnless(shutil.which("yosys"), "Yosys is unavailable")
    def test_yosys_equivalence_distinguishes_equivalent_and_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            equivalent = run_yosys_equivalence(
                reference_sources=[FIXTURES / "equiv_reference.sv"],
                implementation_sources=[FIXTURES / "equiv_implementation.sv"],
                reference_top="equiv_reference",
                implementation_top="equiv_implementation",
                depth=1,
                artifact_root=directory,
            )
            mismatch = run_yosys_equivalence(
                reference_sources=[FIXTURES / "equiv_reference.sv"],
                implementation_sources=[FIXTURES / "equiv_mismatch.sv"],
                reference_top="equiv_reference",
                implementation_top="equiv_mismatch",
                depth=1,
                artifact_root=directory,
            )
            blocked = run_yosys_equivalence(
                reference_sources=[FIXTURES / "equiv_reference.sv"],
                implementation_sources=[FIXTURES / "equiv_implementation.sv"],
                reference_top="equiv_reference",
                implementation_top="missing_top",
                depth=1,
                artifact_root=directory,
            )
            undefined = run_yosys_equivalence(
                reference_sources=[FIXTURES / "equiv_reference.sv"],
                implementation_sources=[FIXTURES / "equiv_implementation.sv"],
                reference_top="equiv_reference",
                implementation_top="equiv_implementation",
                depth=1,
                input_domain="undefined",
                artifact_root=directory,
            )
            defined_script = next(
                Path(path) for path in equivalent["artifacts"] if Path(path).name == "equivalence.ys"
            ).read_text(encoding="utf-8")
            undefined_script = next(
                Path(path) for path in undefined["artifacts"] if Path(path).name == "equivalence.ys"
            ).read_text(encoding="utf-8")
        self.assertEqual(equivalent["status"], "pass", equivalent["summary"])
        self.assertTrue(equivalent["summary"]["equivalent"])
        self.assertEqual(equivalent["summary"]["mode"], "combinational")
        self.assertEqual(equivalent["summary"]["input_domain"], "defined")
        self.assertNotIn("equiv_simple -undef", defined_script)
        self.assertNotIn("equiv_induct -undef", defined_script)
        self.assertEqual(undefined["status"], "pass", undefined["summary"])
        self.assertEqual(undefined["summary"]["input_domain"], "undefined")
        self.assertIn("equiv_simple -undef", undefined_script)
        self.assertIn("equiv_induct -undef", undefined_script)
        self.assertEqual(mismatch["status"], "fail", mismatch["summary"])
        self.assertFalse(mismatch["summary"]["equivalent"])
        self.assertEqual(len(equivalent["subject_hashes"]), 2)
        self.assertEqual(blocked["status"], "blocked", blocked["summary"])
        self.assertIsNone(blocked["summary"]["equivalent"])

    @unittest.skipUnless(shutil.which("sta") or shutil.which("opensta"), "OpenSTA is unavailable")
    def test_opensta_emits_timing_metrics_from_complete_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = run_opensta(
                netlist=STA_FIXTURES / "sta_netlist.v",
                liberty=STA_FIXTURES / "sta.lib",
                constraints=STA_FIXTURES / "sta.sdc",
                top="sta_top",
                artifact_root=directory,
            )
            self.assertEqual(evidence["status"], "pass", evidence["summary"])
            self.assertAlmostEqual(evidence["summary"]["setup_worst_slack"], 7.9, places=6)
            self.assertAlmostEqual(evidence["summary"]["hold_worst_slack"], 2.1, places=6)
            self.assertTrue(evidence["summary"]["timing_met"])
            self.assertEqual(evidence["summary"]["unconstrained_endpoint_count"], 0)
            self.assertEqual(len(evidence["subject_hashes"]), 3)

    @unittest.skipUnless(shutil.which("sta") or shutil.which("opensta"), "OpenSTA is unavailable")
    def test_opensta_negative_slack_is_not_a_passing_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            constraints = Path(directory) / "tight.sdc"
            constraints.write_text(
                "\n".join(
                    [
                        "create_clock -name clk -period 1.0 [get_ports clk]",
                        "set_input_delay -clock clk 1.0 [get_ports data_in]",
                        "set_output_delay -clock clk 1.0 [get_ports data_out]",
                        "set_input_transition 0.01 [get_ports data_in]",
                        "set_load 0.01 [get_ports data_out]",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            evidence = run_opensta(
                netlist=STA_FIXTURES / "sta_netlist.v",
                liberty=STA_FIXTURES / "sta.lib",
                constraints=constraints,
                top="sta_top",
                artifact_root=directory,
            )
        self.assertEqual(evidence["status"], "fail")
        self.assertFalse(evidence["summary"]["timing_met"])
        self.assertLess(evidence["summary"]["setup_worst_slack"], 0.0)

    def test_opensta_rejects_missing_constraints_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RtlAssError) as caught:
                run_opensta(
                    netlist=STA_FIXTURES / "sta_netlist.v",
                    liberty=STA_FIXTURES / "sta.lib",
                    constraints=Path(directory) / "missing.sdc",
                    top="sta_top",
                    artifact_root=directory,
                )
        self.assertEqual(caught.exception.code, "invalid_sta_input")

    def test_unrecognized_unconstrained_report_cannot_default_to_zero(self) -> None:
        from rtl_ass.evidence_sta import _parse_unconstrained_endpoint_count

        with self.assertRaises(RtlAssError) as caught:
            _parse_unconstrained_endpoint_count("warning: report format changed\n")
        self.assertEqual(caught.exception.code, "invalid_sta_report")

    @unittest.skipUnless(shutil.which("sta") or shutil.which("opensta"), "OpenSTA is unavailable")
    def test_opensta_zero_clock_scope_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            constraints = Path(directory) / "no-clock.sdc"
            constraints.write_text("", encoding="utf-8")
            evidence = run_opensta(
                netlist=STA_FIXTURES / "sta_netlist.v",
                liberty=STA_FIXTURES / "sta.lib",
                constraints=constraints,
                top="sta_top",
                artifact_root=directory,
            )
        self.assertEqual(evidence["status"], "blocked")
        self.assertEqual(evidence["summary"]["clock_count"], 0)

    @unittest.skipUnless(shutil.which("sta") or shutil.which("opensta"), "OpenSTA is unavailable")
    def test_opensta_blocks_unconstrained_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = run_opensta(
                netlist=STA_FIXTURES / "sta_netlist.v",
                liberty=STA_FIXTURES / "sta.lib",
                constraints=STA_FIXTURES / "sta_incomplete.sdc",
                top="sta_top",
                artifact_root=directory,
            )
        self.assertEqual(evidence["status"], "blocked", evidence["summary"])
        self.assertGreater(evidence["summary"]["unconstrained_endpoint_count"], 0)


if __name__ == "__main__":
    unittest.main()
