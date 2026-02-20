from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rtl_ass.errors import RtlAssError
from rtl_ass.evidence import (
    CompileManifest,
    EquivalenceInputBundle,
    FormalInputBundle,
    SourceBundle,
    SynthesisInputBundle,
    run_equivalence_evidence,
    run_formal_evidence,
    run_iverilog_simulation,
    run_opensta,
    run_simulation_evidence,
    run_verilator_lint,
    run_verilator_simulation,
    run_yosys_equivalence,
    run_yosys_formal,
    run_yosys_synthesis,
)
from rtl_ass.evidence_common import ToolExecution, ToolVersionProbe, run_tool_command, tool_version

FIXTURES = Path(__file__).parent / "fixtures"
STA_FIXTURES = Path(__file__).parent / "sta_fixtures"


class EvidenceTests(unittest.TestCase):
    def test_failed_version_probe_keeps_diagnostic_out_of_tool_version(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["/tools/iverilog", "-V"],
            returncode=1,
            stdout="Unable to create temporary file /tmp/ivrlg.test\n",
            stderr=None,
        )
        with mock.patch("rtl_ass.evidence_common.subprocess.run", return_value=completed):
            probe = tool_version("/tools/iverilog", ["-V"])

        self.assertEqual(probe.version, "unknown")
        self.assertEqual(probe.status, "failed")
        self.assertEqual(probe.returncode, 1)
        self.assertEqual(probe.diagnostic, "Unable to create temporary file /tmp/ivrlg.test")

    def test_tool_execution_normalizes_timeout_and_launch_failure(self) -> None:
        timeout = subprocess.TimeoutExpired(
            cmd=["/tools/iverilog"],
            timeout=1,
            output=b"partial output",
            stderr=b"partial error",
        )
        with mock.patch("rtl_ass.evidence_common.subprocess.run", side_effect=timeout):
            timed_out = run_tool_command(["/tools/iverilog"], timeout_seconds=1)
        self.assertEqual(timed_out.outcome, "timeout")
        self.assertEqual(timed_out.stdout, "partial output")
        self.assertEqual(timed_out.stderr, "partial error")
        self.assertIsNone(timed_out.returncode)

        with mock.patch("rtl_ass.evidence_common.subprocess.run", side_effect=PermissionError("denied")):
            launch_failed = run_tool_command(["/tools/iverilog"], timeout_seconds=1)
        self.assertEqual(launch_failed.outcome, "launch_failed")
        self.assertEqual(launch_failed.error_type, "PermissionError")
        self.assertEqual(launch_failed.stderr, "denied")
        self.assertIsNone(launch_failed.returncode)

    def test_simulation_compile_failures_are_not_tool_discovery_failures(self) -> None:
        version = ToolVersionProbe(
            version="test-version",
            status="pass",
            command=("/tools/compiler", "--version"),
            returncode=0,
        )
        compile_failure = ToolExecution(
            outcome="completed",
            returncode=1,
            stdout="",
            stderr="compile rejected\n",
        )
        cases = (
            ("iverilog", run_iverilog_simulation),
            ("verilator", run_verilator_simulation),
        )
        for backend, runner in cases:
            with self.subTest(backend=backend), tempfile.TemporaryDirectory() as directory:
                with (
                    mock.patch("rtl_ass.evidence_sim.shutil.which", side_effect=lambda name: f"/tools/{name}"),
                    mock.patch("rtl_ass.evidence_sim.tool_version", return_value=version),
                    mock.patch("rtl_ass.evidence_sim.run_tool_command", return_value=compile_failure),
                ):
                    evidence = runner(
                        [FIXTURES / "counter.sv"],
                        top="counter",
                        artifact_root=directory,
                    )

            self.assertEqual(evidence["status"], "fail")
            self.assertEqual(evidence["summary"]["phase"], "compile")
            self.assertEqual(evidence["summary"]["compile_returncode"], 1)
            self.assertNotIn("missing_executable", evidence["summary"])
            self.assertNotIn("missing_compiled_artifact", evidence["summary"])
            self.assertEqual(evidence["summary"]["tool_version_probe"]["status"], "pass")

    def test_simulation_compile_boundary_distinguishes_discovery_launch_and_output(self) -> None:
        version = ToolVersionProbe(
            version="test-version",
            status="pass",
            command=("/tools/iverilog", "-V"),
            returncode=0,
        )
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch("rtl_ass.evidence_sim.shutil.which", return_value=None):
                unavailable = run_iverilog_simulation([FIXTURES / "counter.sv"], top="counter", artifact_root=directory)
        self.assertEqual(unavailable["status"], "not_available")
        self.assertEqual(unavailable["claim_scope"], "tool discovery only")

        compile_success = ToolExecution(
            outcome="completed",
            returncode=0,
            stdout="",
            stderr="",
        )
        with tempfile.TemporaryDirectory() as directory:
            with (
                mock.patch("rtl_ass.evidence_sim.shutil.which", side_effect=lambda name: f"/tools/{name}"),
                mock.patch("rtl_ass.evidence_sim.tool_version", return_value=version),
                mock.patch("rtl_ass.evidence_sim.run_tool_command", return_value=compile_success),
            ):
                missing_output = run_iverilog_simulation(
                    [FIXTURES / "counter.sv"], top="counter", artifact_root=directory
                )
        self.assertEqual(missing_output["status"], "blocked")
        self.assertTrue(missing_output["summary"]["missing_compiled_artifact"])
        self.assertNotIn("missing_executable", missing_output["summary"])

        with tempfile.TemporaryDirectory() as directory:
            with (
                mock.patch("rtl_ass.evidence_sim.shutil.which", side_effect=lambda name: f"/tools/{name}"),
                mock.patch("rtl_ass.evidence_sim.tool_version", return_value=version),
                mock.patch(
                    "rtl_ass.evidence_sim.run_tool_command",
                    return_value=ToolExecution(
                        outcome="launch_failed",
                        returncode=None,
                        stdout="",
                        stderr="disappeared",
                        error_type="FileNotFoundError",
                    ),
                ),
            ):
                launch_failure = run_iverilog_simulation(
                    [FIXTURES / "counter.sv"], top="counter", artifact_root=directory
                )
        self.assertEqual(launch_failure["status"], "blocked")
        self.assertTrue(launch_failure["summary"]["launch_failed"])
        self.assertEqual(launch_failure["summary"]["launch_error"], "FileNotFoundError")
        self.assertNotIn("compile_returncode", launch_failure["summary"])

    def test_stable_dispatch_boundary_rejects_unknown_backends(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RtlAssError) as simulation:
                run_simulation_evidence(
                    [FIXTURES / "counter.sv"],
                    top="counter",
                    backend="unknown",
                    artifact_root=directory,
                )
            with self.assertRaises(RtlAssError) as formal:
                run_formal_evidence(
                    [FIXTURES / "formal_pass.sv"],
                    top="formal_pass",
                    backend="unknown",
                    depth=2,
                    initialization="defined",
                    artifact_root=directory,
                )
            with self.assertRaises(RtlAssError) as equivalence:
                run_equivalence_evidence(
                    reference_sources=[FIXTURES / "equiv_reference.sv"],
                    implementation_sources=[FIXTURES / "equiv_implementation.sv"],
                    reference_top="equiv_reference",
                    implementation_top="equiv_implementation",
                    backend="unknown",
                    depth=1,
                    artifact_root=directory,
                )
        self.assertEqual(simulation.exception.code, "unsupported_evidence_backend")
        self.assertEqual(formal.exception.code, "unsupported_evidence_backend")
        self.assertEqual(equivalence.exception.code, "unsupported_evidence_backend")

    def test_source_bundle_hash_is_ordered_and_content_bound(self) -> None:
        design = FIXTURES / "counter.sv"
        testbench = FIXTURES / "counter_tb.sv"
        first = SourceBundle.create([design, testbench], "counter_tb")
        second = SourceBundle.create([testbench, design], "counter_tb")
        self.assertNotEqual(first.input_hash, second.input_hash)
        self.assertEqual(first.source_hashes[0]["path"], design.as_posix())
        self.assertEqual(first.source_hashes[0]["index"], 0)

    @unittest.skipUnless(
        shutil.which("iverilog") and shutil.which("vvp") and shutil.which("verilator") and shutil.which("yosys"),
        "Icarus Verilog, Verilator, or Yosys is unavailable",
    )
    def test_compile_manifest_options_are_consumed_by_all_primary_frontends(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            include = root / "include"
            include.mkdir()
            (include / "defs.svh").write_text("`define APPLY_INVERT(value) (~(value))\n", encoding="utf-8")
            design = root / "invert.sv"
            design.write_text(
                '`include "defs.svh"\n'
                "module invert #(parameter WIDTH=1) (input logic [WIDTH-1:0] a, output logic [WIDTH-1:0] y);\n"
                "  assign y = `APPLY_INVERT(a);\n"
                "endmodule\n",
                encoding="utf-8",
            )
            testbench = root / "top_tb.sv"
            testbench.write_text(
                "module top_tb #(parameter WIDTH=1);\n"
                "  logic [WIDTH-1:0] a, y;\n"
                "  invert #(.WIDTH(WIDTH)) dut(.a(a), .y(y));\n"
                "  initial begin a = '0; #1; if (y !== {WIDTH{1'b1}}) $fatal(1); $finish; end\n"
                "endmodule\n",
                encoding="utf-8",
            )
            results = []
            for width in (1, 2, 7, 31, 64):
                simulation_manifest = CompileManifest.create(
                    [testbench],
                    "top_tb",
                    library_files=[design],
                    include_dirs=[include],
                    defines=["FEATURE"],
                    parameters=[f"WIDTH={width}"],
                )
                iverilog = run_iverilog_simulation(
                    simulation_manifest,
                    artifact_root=root / "artifacts" / str(width) / "iverilog",
                )
                verilator = run_verilator_simulation(
                    simulation_manifest,
                    artifact_root=root / "artifacts" / str(width) / "verilator",
                )
                synthesis_manifest = CompileManifest.create(
                    [design],
                    "invert",
                    include_dirs=[include],
                    defines=["FEATURE"],
                    parameters=[f"WIDTH={width}"],
                )
                synthesis = run_yosys_synthesis(
                    synthesis_manifest,
                    artifact_root=root / "artifacts" / str(width) / "yosys",
                )
                results.append((width, iverilog, verilator, synthesis))

        for width, iverilog, verilator, synthesis in results:
            with self.subTest(width=width):
                self.assertEqual(iverilog["status"], "pass", iverilog["summary"])
                self.assertEqual(verilator["status"], "pass", verilator["summary"])
                self.assertEqual(synthesis["status"], "pass", synthesis["summary"])
                self.assertIn(f"-Ptop_tb.WIDTH={width}", iverilog["commands"][0])
                self.assertIn(f"-GWIDTH={width}", verilator["commands"][0])
                self.assertEqual(iverilog["input_hash"], verilator["input_hash"])
                self.assertEqual(len(iverilog["subject_hashes"]), 3)

    def test_formal_and_equivalence_hashes_bind_proof_parameters_and_roles(self) -> None:
        formal_short = FormalInputBundle.create(
            [FIXTURES / "formal_pass.sv"], top="formal_pass", depth=4, initialization="defined"
        )
        formal_deep = FormalInputBundle.create(
            [FIXTURES / "formal_pass.sv"], top="formal_pass", depth=5, initialization="defined"
        )
        formal_parameterized = FormalInputBundle.create(
            CompileManifest.create(
                [FIXTURES / "formal_pass.sv"],
                "formal_pass",
                defines=["FORMAL_MODE"],
            ),
            top=None,
            depth=4,
            initialization="defined",
        )
        self.assertNotEqual(formal_short.input_hash, formal_deep.input_hash)
        self.assertNotEqual(formal_short.input_hash, formal_parameterized.input_hash)
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
        parameterized = EquivalenceInputBundle.create(
            CompileManifest.create([FIXTURES / "equiv_reference.sv"], "equiv_reference", defines=["MODE=1"]),
            CompileManifest.create([FIXTURES / "equiv_implementation.sv"], "equiv_implementation", defines=["MODE=1"]),
            reference_top=None,
            implementation_top=None,
            depth=1,
        )
        self.assertNotEqual(forward.input_hash, reverse.input_hash)
        self.assertNotEqual(forward.input_hash, undefined.input_hash)
        self.assertNotEqual(forward.input_hash, parameterized.input_hash)
        self.assertEqual([item["index"] for item in forward.subject_hashes], [0, 1])

        with self.assertRaises(RtlAssError) as caught:
            EquivalenceInputBundle.create(
                [FIXTURES / "equiv_sequential_reference.sv"],
                [FIXTURES / "equiv_sequential_implementation.sv"],
                reference_top="equiv_sequential_reference",
                implementation_top="equiv_sequential_implementation",
                depth=4,
            )
        self.assertEqual(caught.exception.code, "invalid_equivalence_initialization")
        sequential_zero = EquivalenceInputBundle.create(
            [FIXTURES / "equiv_sequential_reference.sv"],
            [FIXTURES / "equiv_sequential_implementation.sv"],
            reference_top="equiv_sequential_reference",
            implementation_top="equiv_sequential_implementation",
            depth=4,
            initialization="zero",
        )
        self.assertEqual(sequential_zero.initialization, "zero")

    def test_synthesis_bundle_binds_liberty_and_rejects_unsafe_inputs(self) -> None:
        generic = SynthesisInputBundle.create([FIXTURES / "mapped_logic.sv"], top="mapped_logic", liberty=None)
        mapped = SynthesisInputBundle.create(
            [FIXTURES / "mapped_logic.sv"],
            top="mapped_logic",
            liberty=FIXTURES / "mapped_cells.lib",
        )
        self.assertNotEqual(generic.input_hash, mapped.input_hash)
        self.assertEqual(mapped.subject_hashes[-1]["path"], (FIXTURES / "mapped_cells.lib").as_posix())
        self.assertEqual(mapped.option_summary()["synthesis_mode"], "liberty-mapped")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wrong_suffix = root / "cells.txt"
            wrong_suffix.write_text("library(test) {}\n", encoding="utf-8")
            symlink = root / "cells.lib"
            symlink.symlink_to(FIXTURES / "mapped_cells.lib")
            for invalid in (wrong_suffix, symlink):
                with self.subTest(path=invalid), self.assertRaises(RtlAssError) as caught:
                    SynthesisInputBundle.create([FIXTURES / "mapped_logic.sv"], top="mapped_logic", liberty=invalid)
                self.assertEqual(caught.exception.code, "invalid_synthesis_liberty")

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
            self.assertIn("synth -top counter -noabc", script)
            self.assertNotIn("abc -liberty", script)

    @unittest.skipUnless(shutil.which("yosys"), "Yosys is unavailable")
    def test_yosys_mapped_synthesis_emits_liberty_bound_verilog_netlist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = run_yosys_synthesis(
                [FIXTURES / "mapped_logic.sv"],
                top="mapped_logic",
                liberty=FIXTURES / "mapped_cells.lib",
                artifact_root=directory,
            )

            self.assertEqual(evidence["status"], "pass", evidence["summary"])
            self.assertEqual(evidence["summary"]["compile_manifest"]["synthesis_mode"], "liberty-mapped")
            self.assertEqual(len(evidence["subject_hashes"]), 2)
            artifacts = {Path(path).name: Path(path) for path in evidence["artifacts"]}
            self.assertIn("netlist.v", artifacts)
            script = artifacts["synthesis.ys"].read_text(encoding="utf-8")
            self.assertLess(script.index("read_liberty -lib"), script.index("read_verilog"))
            self.assertIn("abc -fast -liberty", script)
            netlist = artifacts["netlist.v"].read_text(encoding="utf-8")
            self.assertIn("NAND2_X1", netlist)

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
        self.assertNotIn("equiv_induct", undefined_script)
        self.assertEqual(mismatch["status"], "fail", mismatch["summary"])
        self.assertFalse(mismatch["summary"]["equivalent"])
        self.assertEqual(len(equivalent["subject_hashes"]), 2)
        self.assertEqual(blocked["status"], "blocked", blocked["summary"])
        self.assertIsNone(blocked["summary"]["equivalent"])

    @unittest.skipUnless(shutil.which("yosys"), "Yosys is unavailable")
    def test_yosys_sequential_equivalence_requires_and_executes_initialization_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            equivalent = run_yosys_equivalence(
                reference_sources=[FIXTURES / "equiv_sequential_reference.sv"],
                implementation_sources=[FIXTURES / "equiv_sequential_implementation.sv"],
                reference_top="equiv_sequential_reference",
                implementation_top="equiv_sequential_implementation",
                depth=4,
                initialization="zero",
                artifact_root=directory,
            )
            mismatch = run_yosys_equivalence(
                reference_sources=[FIXTURES / "equiv_sequential_reference.sv"],
                implementation_sources=[FIXTURES / "equiv_sequential_mismatch.sv"],
                reference_top="equiv_sequential_reference",
                implementation_top="equiv_sequential_mismatch",
                depth=4,
                initialization="zero",
                artifact_root=directory,
            )
            script = next(
                Path(path) for path in equivalent["artifacts"] if Path(path).name == "equivalence.ys"
            ).read_text(encoding="utf-8")
        self.assertEqual(equivalent["status"], "pass", equivalent["summary"])
        self.assertTrue(equivalent["summary"]["equivalent"])
        self.assertEqual(equivalent["summary"]["initialization"], "zero")
        self.assertIn("sat -verify -prove-asserts", script)
        self.assertIn("-set-init-zero", script)
        self.assertNotIn("equiv_induct", script)
        self.assertEqual(mismatch["status"], "fail", mismatch["summary"])
        self.assertFalse(mismatch["summary"]["equivalent"])

    @unittest.skipUnless(shutil.which("yosys"), "Yosys is unavailable")
    def test_yosys_sequential_equivalence_does_not_ignore_source_initial_state_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RtlAssError) as caught:
                run_yosys_equivalence(
                    reference_sources=[FIXTURES / "equiv_initial_zero.sv"],
                    implementation_sources=[FIXTURES / "equiv_initial_one.sv"],
                    reference_top="equiv_initial_zero",
                    implementation_top="equiv_initial_one",
                    depth=4,
                    artifact_root=directory,
                )
            mismatch = run_yosys_equivalence(
                reference_sources=[FIXTURES / "equiv_initial_zero.sv"],
                implementation_sources=[FIXTURES / "equiv_initial_one.sv"],
                reference_top="equiv_initial_zero",
                implementation_top="equiv_initial_one",
                depth=4,
                initialization="zero",
                artifact_root=directory,
            )
        self.assertEqual(caught.exception.code, "invalid_equivalence_initialization")
        self.assertEqual(mismatch["status"], "fail", mismatch["summary"])
        self.assertFalse(mismatch["summary"]["equivalent"])
        self.assertTrue(mismatch["summary"]["source_initial_values_preserved"])

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

    def test_opensta_launch_failure_is_blocked_not_a_timing_failure(self) -> None:
        launch_failure = ToolExecution(
            outcome="launch_failed",
            returncode=None,
            stdout="",
            stderr="permission denied",
            error_type="PermissionError",
        )
        version = ToolVersionProbe(
            version="test-version",
            status="pass",
            command=("/tools/sta", "-version"),
            returncode=0,
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch("rtl_ass.evidence_sta.shutil.which", return_value="/tools/sta"),
            mock.patch("rtl_ass.evidence_sta.tool_version", return_value=version),
            mock.patch("rtl_ass.evidence_sta.run_tool_command", return_value=launch_failure),
        ):
            evidence = run_opensta(
                netlist=STA_FIXTURES / "sta_netlist.v",
                liberty=STA_FIXTURES / "sta.lib",
                constraints=STA_FIXTURES / "sta.sdc",
                top="sta_top",
                artifact_root=directory,
            )

        self.assertEqual(evidence["status"], "blocked")
        self.assertTrue(evidence["summary"]["launch_failed"])
        self.assertNotIn("returncode", evidence["summary"])

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
