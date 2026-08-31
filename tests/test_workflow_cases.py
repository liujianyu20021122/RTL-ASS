from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from evals.run_codex_ab import _prepare_workspace
from evals.workflow_cases import CASES, get_case
from rtl_ass.waveform import first_divergence_waveform

ROOT = Path(__file__).resolve().parents[1]
OPEN_GRADER_TOOLS = all(shutil.which(tool) for tool in ("iverilog", "vvp", "verilator", "yosys"))


class WorkflowCaseTests(unittest.TestCase):
    def test_registry_has_distinct_public_and_private_boundaries(self) -> None:
        self.assertEqual(
            set(CASES),
            {
                "repair-non-power-of-two-fifo",
                "spec-ready-valid-register",
                "attribute-nba-scoreboard",
                "systemverilog-signed-width",
                "timing-refine-priority-path",
                "waveform-first-divergence",
            },
        )
        for case in CASES.values():
            with self.subTest(case=case.identifier):
                self.assertTrue(case.public_fixture.is_dir())
                self.assertTrue((case.public_fixture.parent / "private").is_dir())
                self.assertNotIn("private", case.public_fixture.parts)

    def test_executable_required_evidence_matches_public_manifest(self) -> None:
        manifest = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))
        declared = {case["id"]: frozenset(case["required_evidence"]) for case in manifest["cases"]}

        self.assertEqual(declared, {identifier: case.required_evidence for identifier, case in CASES.items()})

    @unittest.skipUnless(OPEN_GRADER_TOOLS, "open RTL grader tools are unavailable")
    def test_public_broken_fixtures_do_not_pass_independent_graders(self) -> None:
        for identifier in (
            "spec-ready-valid-register",
            "attribute-nba-scoreboard",
            "systemverilog-signed-width",
            "timing-refine-priority-path",
            "waveform-first-divergence",
        ):
            with self.subTest(case=identifier), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                case = get_case(identifier)
                workspace = root / "workspace"
                initial = _prepare_workspace(workspace, "off", case)

                grade = case.grade(workspace, root / "grade", initial)

                self.assertFalse(grade["correct"])

    @unittest.skipUnless(OPEN_GRADER_TOOLS, "open RTL grader tools are unavailable")
    def test_ready_valid_reference_passes_hidden_and_mutation_grades(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = get_case("spec-ready-valid-register")
            workspace = root / "workspace"
            initial = _prepare_workspace(workspace, "off", case)
            shutil.copy2(
                ROOT / "library" / "starter" / "rtl" / "ready_valid_register.sv",
                workspace / "rtl" / "ready_valid_register.sv",
            )
            shutil.copy2(
                ROOT / "library" / "starter" / "tb" / "ready_valid_register_tb.sv",
                workspace / "tb" / "ready_valid_register_tb.sv",
            )

            grade = case.grade(workspace, root / "grade", initial)

            self.assertTrue(grade["correct"])
            self.assertEqual(grade["grader_statuses"]["mutation_rejected"], "fail")

    @unittest.skipUnless(OPEN_GRADER_TOOLS, "open RTL grader tools are unavailable")
    def test_attribution_reference_changes_only_testbench_and_rejects_mutant(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = get_case("attribute-nba-scoreboard")
            workspace = root / "workspace"
            initial = _prepare_workspace(workspace, "off", case)
            testbench = workspace / "tb" / "registered_pulse_tb.sv"
            source = testbench.read_text(encoding="utf-8").replace(
                "        expected_data = data_i;\n        if (valid_o",
                "        expected_data = data_i;\n        @(negedge clk);\n        if (valid_o",
            )
            testbench.write_text(source, encoding="utf-8")
            diagnosis = {
                "schema_version": "1.0",
                "classification": "testbench-sampling-region",
                "first_divergence_time": 35000,
                "expected_valid": 1,
                "actual_valid": 0,
                "responsible_file": "tb/registered_pulse_tb.sv",
            }
            (workspace / "artifacts" / "diagnosis.json").write_text(json.dumps(diagnosis) + "\n", encoding="utf-8")

            grade = case.grade(workspace, root / "grade", initial)

            self.assertTrue(grade["correct"])
            self.assertEqual(grade["tracked_changed_files"], ["tb/registered_pulse_tb.sv"])
            self.assertEqual(grade["grader_statuses"]["mutation_rejected"], "fail")

    @unittest.skipUnless(OPEN_GRADER_TOOLS, "open RTL grader tools are unavailable")
    def test_signed_width_reference_passes_hidden_and_equivalence_grades(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = get_case("systemverilog-signed-width")
            workspace = root / "workspace"
            initial = _prepare_workspace(workspace, "off", case)
            reference = (
                ROOT
                / "evals"
                / "workflow_cases"
                / "systemverilog_signed_width"
                / "private"
                / "sat_add_pipe_reference.sv"
            ).read_text(encoding="utf-8")
            (workspace / "rtl" / "sat_add_pipe.sv").write_text(
                reference.replace("sat_add_pipe_reference", "sat_add_pipe"), encoding="utf-8"
            )

            grade = case.grade(workspace, root / "grade", initial)

            self.assertTrue(grade["correct"])
            self.assertEqual(grade["grader_statuses"]["equivalence"], "pass")

    @unittest.skipUnless(
        OPEN_GRADER_TOOLS and (shutil.which("sta") or shutil.which("opensta")),
        "open RTL/STA grader tools are unavailable",
    )
    def test_timing_reference_closes_sta_and_preserves_function(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = get_case("timing-refine-priority-path")
            workspace = root / "workspace"
            initial = _prepare_workspace(workspace, "off", case)
            reference = (
                ROOT
                / "evals"
                / "workflow_cases"
                / "timing_refine_priority_path"
                / "private"
                / "priority_select_reference.v"
            ).read_text(encoding="utf-8")
            (workspace / "rtl" / "priority_select.v").write_text(
                reference.replace("priority_select_reference", "priority_select"), encoding="utf-8"
            )

            grade = case.grade(workspace, root / "grade", initial)

            self.assertTrue(grade["correct"])
            self.assertEqual(grade["grader_statuses"]["sta"], "pass")
            self.assertGreaterEqual(grade["timing_summary"]["setup_worst_slack"], 0.0)
            self.assertGreaterEqual(grade["timing_summary"]["hold_worst_slack"], 0.0)
            self.assertEqual(grade["timing_summary"]["unconstrained_endpoint_count"], 0)

    @unittest.skipUnless(shutil.which("fst2vcd"), "GTKWave FST converter is unavailable")
    def test_waveform_reference_binds_fst_conversion_and_first_divergence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = get_case("waveform-first-divergence")
            workspace = root / "workspace"
            initial = _prepare_workspace(workspace, "off", case)
            trace = workspace / "trace" / "priority_divergence.fst"
            divergence = first_divergence_waveform(
                trace,
                expected="priority_monitor_tb.expected_o",
                actual="priority_monitor_tb.actual_o",
                start_time=0,
                end_time=25,
            )
            (workspace / "artifacts" / "wave-divergence.json").write_text(
                json.dumps(divergence) + "\n", encoding="utf-8"
            )
            diagnosis = {
                "schema_version": "1.0",
                "classification": "missing-no-request-default",
                "first_divergence_time": 20,
                "expected_value": "0",
                "actual_value": "1",
                "responsible_file": "rtl/priority_monitor.sv",
            }
            (workspace / "artifacts" / "diagnosis.json").write_text(json.dumps(diagnosis) + "\n", encoding="utf-8")

            grade = case.grade(workspace, root / "grade", initial)

            self.assertTrue(grade["correct"])
            self.assertTrue(grade["complete"])
            self.assertEqual(grade["grader_statuses"]["saved_fst_divergence"], "pass")

    @unittest.skipUnless(shutil.which("vcd2fst"), "GTKWave VCD-to-FST converter is unavailable")
    def test_public_fst_reproduces_byte_for_byte_from_private_source_vcd(self) -> None:
        source = (
            ROOT
            / "evals"
            / "workflow_cases"
            / "waveform_first_divergence"
            / "private"
            / "priority_divergence_source.vcd"
        )
        expected = (
            ROOT
            / "evals"
            / "workflow_cases"
            / "waveform_first_divergence"
            / "public"
            / "trace"
            / "priority_divergence.fst"
        )
        with tempfile.TemporaryDirectory() as temporary:
            generated = Path(temporary) / "priority_divergence.fst"
            subprocess.run(["vcd2fst", str(source), str(generated)], check=True, capture_output=True)

            self.assertEqual(generated.read_bytes(), expected.read_bytes())


if __name__ == "__main__":
    unittest.main()
