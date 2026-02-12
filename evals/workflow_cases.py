"""First-party workflow cases and independent open-tool graders."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from rtl_ass.evidence import (
    run_iverilog_simulation,
    run_opensta,
    run_verilator_lint,
    run_yosys_equivalence,
    run_yosys_synthesis,
)
from rtl_ass.integrity import hash_file
from rtl_ass.waveform import first_divergence_waveform

ROOT = Path(__file__).resolve().parents[1]
CASES_ROOT = ROOT / "evals" / "workflow_cases"
GradeFunction = Callable[[Path, Path, Mapping[str, str]], dict[str, Any]]


@dataclass(frozen=True)
class WorkflowCase:
    identifier: str
    prompt: str
    public_fixture: Path
    required_evidence: frozenset[str]
    grade: GradeFunction


def _regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _git_state(workspace: Path) -> tuple[list[str], list[str]]:
    changed = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=workspace,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    status = subprocess.run(
        ["git", "status", "--short"],
        cwd=workspace,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return changed.stdout.splitlines(), status.stdout.splitlines()


def _evidence_view(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in items:
        evidence_file = item.get("evidence_file")
        records.append(
            {
                "kind": item.get("kind"),
                "status": item.get("status"),
                "input_hash": item.get("input_hash"),
                "evidence_file_hash": (
                    hash_file(evidence_file)
                    if isinstance(evidence_file, str) and Path(evidence_file).is_file()
                    else None
                ),
            }
        )
    return records


def _fifo_grade(workspace: Path, run_root: Path, initial: Mapping[str, str]) -> dict[str, Any]:
    candidate = workspace / "rtl" / "sync_fifo.sv"
    visible = workspace / "tb" / "sync_fifo_visible_tb.sv"
    hidden = CASES_ROOT / "non_power_two_fifo" / "private" / "sync_fifo_hidden_tb.sv"
    if not _regular_file(candidate):
        return {"correct": False, "error": "candidate_not_regular_file"}
    evidence_root = run_root / "grader-evidence"
    evidence = [
        run_verilator_lint([candidate], top="sync_fifo", artifact_root=evidence_root),
        run_iverilog_simulation([candidate, hidden], top="sync_fifo_hidden_tb", artifact_root=evidence_root),
        run_yosys_synthesis([candidate], top="sync_fifo", artifact_root=evidence_root),
    ]
    statuses = {item["kind"]: item["status"] for item in evidence}
    candidate_hash = hash_file(candidate)
    visible_hash = hash_file(visible) if _regular_file(visible) else None
    changed, git_status = _git_state(workspace)
    protected = visible_hash == initial.get("tb/sync_fifo_visible_tb.sv")
    source_changed = candidate_hash != initial.get("rtl/sync_fifo.sv")
    return {
        "correct": (
            all(statuses.get(kind) == "pass" for kind in ("lint", "simulation", "synthesis"))
            and protected
            and source_changed
            and changed == ["rtl/sync_fifo.sv"]
        ),
        "grader_statuses": statuses,
        "candidate_hashes": {"rtl/sync_fifo.sv": candidate_hash},
        "source_changed": source_changed,
        "protected_files_unchanged": protected,
        "tracked_changed_files": changed,
        "git_status": git_status,
        "expected_agent_evidence_subjects": {
            "lint": [candidate_hash],
            "simulation": [candidate_hash, visible_hash],
            "synthesis": [candidate_hash],
        },
        "evidence": _evidence_view(evidence),
    }


def _ready_valid_grade(workspace: Path, run_root: Path, initial: Mapping[str, str]) -> dict[str, Any]:
    rtl = workspace / "rtl" / "ready_valid_register.sv"
    testbench = workspace / "tb" / "ready_valid_register_tb.sv"
    spec = workspace / "SPEC.md"
    private = CASES_ROOT / "spec_ready_valid_register" / "private"
    if not _regular_file(rtl) or not _regular_file(testbench):
        return {"correct": False, "error": "required_candidate_file_missing"}
    evidence_root = run_root / "grader-evidence"
    lint = run_verilator_lint([rtl], top="ready_valid_register", artifact_root=evidence_root)
    visible = run_iverilog_simulation(
        [rtl, testbench], top="ready_valid_register_tb", artifact_root=evidence_root / "candidate-tb"
    )
    hidden = run_iverilog_simulation(
        [rtl, private / "ready_valid_register_hidden_tb.sv"],
        top="ready_valid_register_hidden_tb",
        artifact_root=evidence_root / "hidden-tb",
    )
    mutant = run_iverilog_simulation(
        [private / "ready_valid_register_mutant.sv", testbench],
        top="ready_valid_register_tb",
        artifact_root=evidence_root / "mutation",
    )
    synthesis = run_yosys_synthesis([rtl], top="ready_valid_register", artifact_root=evidence_root)
    evidence = [lint, visible, hidden, mutant, synthesis]
    statuses = {
        "lint": lint["status"],
        "candidate_testbench": visible["status"],
        "hidden_simulation": hidden["status"],
        "mutation_rejected": mutant["status"],
        "synthesis": synthesis["status"],
    }
    rtl_hash = hash_file(rtl)
    testbench_hash = hash_file(testbench)
    spec_unchanged = _regular_file(spec) and hash_file(spec) == initial.get("SPEC.md")
    changed, git_status = _git_state(workspace)
    return {
        "correct": (
            statuses["lint"] == "pass"
            and statuses["candidate_testbench"] == "pass"
            and statuses["hidden_simulation"] == "pass"
            and statuses["mutation_rejected"] == "fail"
            and statuses["synthesis"] == "pass"
            and spec_unchanged
        ),
        "grader_statuses": statuses,
        "candidate_hashes": {
            "rtl/ready_valid_register.sv": rtl_hash,
            "tb/ready_valid_register_tb.sv": testbench_hash,
        },
        "protected_files_unchanged": spec_unchanged,
        "tracked_changed_files": changed,
        "git_status": git_status,
        "expected_agent_evidence_subjects": {
            "lint": [rtl_hash],
            "simulation": [rtl_hash, testbench_hash],
            "synthesis": [rtl_hash],
        },
        "evidence": _evidence_view(evidence),
    }


def _load_exact_json(path: Path, expected: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
    if not _regular_file(path):
        return False, None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False, None
    return value == expected, value if isinstance(value, dict) else None


def _load_diagnosis(path: Path) -> tuple[bool, dict[str, Any] | None]:
    expected = {
        "schema_version": "1.0",
        "classification": "testbench-sampling-region",
        "first_divergence_time": 35000,
        "expected_valid": 1,
        "actual_valid": 0,
        "responsible_file": "tb/registered_pulse_tb.sv",
    }
    return _load_exact_json(path, expected)


def _attribution_grade(workspace: Path, run_root: Path, initial: Mapping[str, str]) -> dict[str, Any]:
    rtl = workspace / "rtl" / "registered_pulse.sv"
    testbench = workspace / "tb" / "registered_pulse_tb.sv"
    diagnosis_path = workspace / "artifacts" / "diagnosis.json"
    private = CASES_ROOT / "attribute_nba_scoreboard" / "private"
    if not _regular_file(rtl) or not _regular_file(testbench):
        return {"correct": False, "error": "required_candidate_file_missing"}
    evidence_root = run_root / "grader-evidence"
    visible = run_iverilog_simulation(
        [rtl, testbench], top="registered_pulse_tb", artifact_root=evidence_root / "candidate-tb"
    )
    hidden = run_iverilog_simulation(
        [rtl, private / "registered_pulse_hidden_tb.sv"],
        top="registered_pulse_hidden_tb",
        artifact_root=evidence_root / "hidden-tb",
    )
    mutant = run_iverilog_simulation(
        [private / "registered_pulse_mutant.sv", testbench],
        top="registered_pulse_tb",
        artifact_root=evidence_root / "mutation",
    )
    lint = run_verilator_lint([rtl], top="registered_pulse", artifact_root=evidence_root)
    evidence = [visible, hidden, mutant, lint]
    statuses = {
        "candidate_testbench": visible["status"],
        "hidden_simulation": hidden["status"],
        "mutation_rejected": mutant["status"],
        "lint": lint["status"],
    }
    rtl_hash = hash_file(rtl)
    testbench_hash = hash_file(testbench)
    rtl_unchanged = rtl_hash == initial.get("rtl/registered_pulse.sv")
    testbench_changed = testbench_hash != initial.get("tb/registered_pulse_tb.sv")
    diagnosis_valid, diagnosis = _load_diagnosis(diagnosis_path)
    changed, git_status = _git_state(workspace)
    return {
        "correct": (
            statuses["candidate_testbench"] == "pass"
            and statuses["hidden_simulation"] == "pass"
            and statuses["mutation_rejected"] == "fail"
            and statuses["lint"] == "pass"
            and rtl_unchanged
            and testbench_changed
            and diagnosis_valid
            and changed == ["tb/registered_pulse_tb.sv"]
        ),
        "grader_statuses": statuses,
        "candidate_hashes": {
            "rtl/registered_pulse.sv": rtl_hash,
            "tb/registered_pulse_tb.sv": testbench_hash,
        },
        "diagnosis_valid": diagnosis_valid,
        "diagnosis": diagnosis,
        "protected_files_unchanged": rtl_unchanged,
        "responsible_file_changed": testbench_changed,
        "tracked_changed_files": changed,
        "git_status": git_status,
        "expected_agent_evidence_subjects": {
            "simulation": [rtl_hash, testbench_hash],
            "waveform": [],
        },
        "evidence": _evidence_view(evidence),
    }


def _signed_width_grade(workspace: Path, run_root: Path, initial: Mapping[str, str]) -> dict[str, Any]:
    rtl = workspace / "rtl" / "sat_add_pipe.sv"
    visible_tb = workspace / "tb" / "sat_add_pipe_visible_tb.sv"
    private = CASES_ROOT / "systemverilog_signed_width" / "private"
    reference = private / "sat_add_pipe_reference.sv"
    hidden_tb = private / "sat_add_pipe_hidden_tb.sv"
    if not _regular_file(rtl):
        return {"correct": False, "error": "candidate_not_regular_file"}
    evidence_root = run_root / "grader-evidence"
    lint = run_verilator_lint([rtl], top="sat_add_pipe", artifact_root=evidence_root)
    visible = run_iverilog_simulation(
        [rtl, visible_tb], top="sat_add_pipe_visible_tb", artifact_root=evidence_root / "visible"
    )
    hidden = run_iverilog_simulation(
        [rtl, hidden_tb], top="sat_add_pipe_hidden_tb", artifact_root=evidence_root / "hidden"
    )
    synthesis = run_yosys_synthesis([rtl], top="sat_add_pipe", artifact_root=evidence_root)
    equivalence = run_yosys_equivalence(
        reference_sources=[reference],
        implementation_sources=[rtl],
        reference_top="sat_add_pipe_reference",
        implementation_top="sat_add_pipe",
        depth=4,
        artifact_root=evidence_root,
    )
    evidence = [lint, visible, hidden, synthesis, equivalence]
    statuses = {
        "lint": lint["status"],
        "visible_simulation": visible["status"],
        "hidden_simulation": hidden["status"],
        "synthesis": synthesis["status"],
        "equivalence": equivalence["status"],
    }
    rtl_hash = hash_file(rtl)
    visible_hash = hash_file(visible_tb) if _regular_file(visible_tb) else None
    protected = visible_hash == initial.get("tb/sat_add_pipe_visible_tb.sv")
    source_changed = rtl_hash != initial.get("rtl/sat_add_pipe.sv")
    changed, git_status = _git_state(workspace)
    return {
        "correct": (
            all(status == "pass" for status in statuses.values())
            and protected
            and source_changed
            and changed == ["rtl/sat_add_pipe.sv"]
        ),
        "grader_statuses": statuses,
        "candidate_hashes": {"rtl/sat_add_pipe.sv": rtl_hash},
        "source_changed": source_changed,
        "protected_files_unchanged": protected,
        "tracked_changed_files": changed,
        "git_status": git_status,
        "expected_agent_evidence_subjects": {
            "lint": [rtl_hash],
            "simulation": [rtl_hash, visible_hash],
            "equivalence": [rtl_hash],
        },
        "evidence": _evidence_view(evidence),
    }


def _timing_grade(workspace: Path, run_root: Path, initial: Mapping[str, str]) -> dict[str, Any]:
    rtl = workspace / "rtl" / "priority_select.v"
    cells = workspace / "lib" / "cells.v"
    liberty = workspace / "lib" / "cells.lib"
    constraints = workspace / "constraints" / "priority_select.sdc"
    visible_tb = workspace / "tb" / "priority_select_visible_tb.sv"
    private = CASES_ROOT / "timing_refine_priority_path" / "private"
    reference = private / "priority_select_reference.v"
    hidden_tb = private / "priority_select_hidden_tb.sv"
    required_files = (rtl, cells, liberty, constraints, visible_tb)
    if not all(_regular_file(path) for path in required_files):
        return {"correct": False, "error": "required_timing_input_missing"}

    evidence_root = run_root / "grader-evidence"
    lint = run_verilator_lint([cells, rtl], top="priority_select", artifact_root=evidence_root)
    visible = run_iverilog_simulation(
        [cells, rtl, visible_tb], top="priority_select_visible_tb", artifact_root=evidence_root / "visible"
    )
    hidden = run_iverilog_simulation(
        [cells, rtl, hidden_tb], top="priority_select_hidden_tb", artifact_root=evidence_root / "hidden"
    )
    synthesis = run_yosys_synthesis([cells, rtl], top="priority_select", artifact_root=evidence_root)
    equivalence = run_yosys_equivalence(
        reference_sources=[cells, reference],
        implementation_sources=[cells, rtl],
        reference_top="priority_select_reference",
        implementation_top="priority_select",
        depth=1,
        artifact_root=evidence_root,
    )
    sta = run_opensta(
        netlist=rtl,
        liberty=liberty,
        constraints=constraints,
        top="priority_select",
        artifact_root=evidence_root,
    )
    evidence = [lint, visible, hidden, synthesis, equivalence, sta]
    statuses = {
        "lint": lint["status"],
        "visible_simulation": visible["status"],
        "hidden_simulation": hidden["status"],
        "synthesis": synthesis["status"],
        "equivalence": equivalence["status"],
        "sta": sta["status"],
    }
    hashes = {path.relative_to(workspace).as_posix(): hash_file(path) for path in required_files}
    protected_paths = (
        "SPEC.md",
        "lib/cells.v",
        "lib/cells.lib",
        "constraints/priority_select.sdc",
        "tb/priority_select_visible_tb.sv",
    )
    protected = all(hashes.get(path, hash_file(workspace / path)) == initial.get(path) for path in protected_paths)
    source_changed = hashes["rtl/priority_select.v"] != initial.get("rtl/priority_select.v")
    changed, git_status = _git_state(workspace)
    return {
        "correct": (
            all(status == "pass" for status in statuses.values())
            and protected
            and source_changed
            and changed == ["rtl/priority_select.v"]
        ),
        "grader_statuses": statuses,
        "timing_summary": sta.get("summary"),
        "candidate_hashes": {"rtl/priority_select.v": hashes["rtl/priority_select.v"]},
        "source_changed": source_changed,
        "protected_files_unchanged": protected,
        "tracked_changed_files": changed,
        "git_status": git_status,
        "expected_agent_evidence_subjects": {
            "simulation": [
                hashes["rtl/priority_select.v"],
                hashes["lib/cells.v"],
                hashes["tb/priority_select_visible_tb.sv"],
            ],
            "synthesis": [hashes["rtl/priority_select.v"], hashes["lib/cells.v"]],
            "equivalence": [hashes["rtl/priority_select.v"]],
            "sta": [
                hashes["rtl/priority_select.v"],
                hashes["lib/cells.lib"],
                hashes["constraints/priority_select.sdc"],
            ],
        },
        "evidence": _evidence_view(evidence),
    }


def _saved_fst_divergence(workspace: Path, trace_hash: str) -> tuple[bool, dict[str, Any] | None]:
    artifacts = workspace / "artifacts"
    for path in sorted(artifacts.rglob("*.json")):
        if path.name == "diagnosis.json" or not _regular_file(path):
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(value, dict):
            continue
        divergence = value.get("first_divergence")
        window = value.get("window")
        conversion = value.get("conversion")
        tool = conversion.get("tool") if isinstance(conversion, dict) else None
        if not isinstance(divergence, dict) or not isinstance(window, dict) or not isinstance(tool, dict):
            continue
        assert isinstance(conversion, dict)
        start = window.get("start")
        end = window.get("end")
        valid_window = (
            isinstance(start, int)
            and not isinstance(start, bool)
            and isinstance(end, int)
            and not isinstance(end, bool)
            and start <= 20 <= end
            and end - start <= 100
        )
        valid_hashes = all(
            isinstance(candidate, str) and len(candidate) == 64
            for candidate in (
                conversion.get("converted_vcd_hash"),
                tool.get("binary_hash"),
            )
        )
        if (
            value.get("kind") == "fst-first-divergence"
            and value.get("status") == "found"
            and value.get("waveform_hash") == trace_hash
            and divergence
            == {
                "time": 20,
                "expected_signal": "priority_monitor_tb.expected_o",
                "expected_value": "0",
                "actual_signal": "priority_monitor_tb.actual_o",
                "actual_value": "1",
            }
            and valid_window
            and tool.get("name") == "fst2vcd"
            and valid_hashes
        ):
            return True, value
    return False, None


def _waveform_divergence_grade(workspace: Path, run_root: Path, initial: Mapping[str, str]) -> dict[str, Any]:
    del run_root
    trace = workspace / "trace" / "priority_divergence.fst"
    diagnosis_path = workspace / "artifacts" / "diagnosis.json"
    if not _regular_file(trace):
        return {"correct": False, "error": "fst_trace_missing"}
    trace_hash = hash_file(trace)
    expected_diagnosis = {
        "schema_version": "1.0",
        "classification": "missing-no-request-default",
        "first_divergence_time": 20,
        "expected_value": "0",
        "actual_value": "1",
        "responsible_file": "rtl/priority_monitor.sv",
    }
    diagnosis_valid, diagnosis = _load_exact_json(diagnosis_path, expected_diagnosis)
    saved_evidence_valid, saved_evidence = _saved_fst_divergence(workspace, trace_hash)
    external = first_divergence_waveform(
        trace,
        expected="priority_monitor_tb.expected_o",
        actual="priority_monitor_tb.actual_o",
        start_time=0,
        end_time=25,
    )
    external_valid = (
        external.get("kind") == "fst-first-divergence"
        and external.get("status") == "found"
        and external.get("waveform_hash") == trace_hash
        and external.get("first_divergence", {}).get("time") == 20
    )
    protected = all(
        _regular_file(workspace / relative) and hash_file(workspace / relative) == digest
        for relative, digest in initial.items()
        if relative != "repository_head"
    )
    changed, git_status = _git_state(workspace)
    correct = diagnosis_valid and external_valid and protected and changed == []
    return {
        "correct": correct,
        "complete": correct and saved_evidence_valid,
        "grader_statuses": {
            "diagnosis": "pass" if diagnosis_valid else "fail",
            "saved_fst_divergence": "pass" if saved_evidence_valid else "fail",
            "external_fst_divergence": "pass" if external_valid else "fail",
        },
        "candidate_hashes": {"trace/priority_divergence.fst": trace_hash},
        "diagnosis": diagnosis,
        "saved_waveform_evidence": saved_evidence,
        "protected_files_unchanged": protected,
        "tracked_changed_files": changed,
        "git_status": git_status,
        "expected_agent_evidence_subjects": {"waveform": [trace_hash]},
        "evidence": [
            {
                "kind": "waveform",
                "status": "pass" if external_valid else "fail",
                "input_hash": trace_hash,
                "evidence_file_hash": None,
            }
        ],
    }


CASES = {
    "repair-non-power-of-two-fifo": WorkflowCase(
        identifier="repair-non-power-of-two-fifo",
        prompt="""Diagnose and minimally repair the depth-three synchronous FIFO in this repository.
Preserve its module interface, reset behavior, externally visible latency, parameterization, and test intent.
Do not weaken or rewrite the supplied testbench. Run the strongest relevant open-source verification available.
In the final response, state the root cause, exact files changed, and executed evidence with its scope.
""",
        public_fixture=CASES_ROOT / "non_power_two_fifo" / "public",
        required_evidence=frozenset({"lint", "simulation", "synthesis"}),
        grade=_fifo_grade,
    ),
    "spec-ready-valid-register": WorkflowCase(
        identifier="spec-ready-valid-register",
        prompt="""Implement the one-entry ready/valid register and self-checking testbench described by SPEC.md.
Create the exact requested files and preserve the declared interface, reset behavior, latency, and backpressure semantics.
Run relevant open-source verification. Do not weaken the contract or omit timeout and failure checks.
In the final response, state the files created, verification evidence, and remaining scope.
""",
        public_fixture=CASES_ROOT / "spec_ready_valid_register" / "public",
        required_evidence=frozenset({"lint", "simulation", "synthesis"}),
        grade=_ready_valid_grade,
    ),
    "attribute-nba-scoreboard": WorkflowCase(
        identifier="attribute-nba-scoreboard",
        prompt="""Diagnose the supplied registered-pulse failure under the contract in SPEC.md.
Preserve competing RTL and testbench hypotheses until the trace resolves attribution. Repair only the responsible component.
Use the failing VCD and create artifacts/diagnosis.json with the exact schema requested by SPEC.md.
Run focused and regression verification. Do not add an arbitrary delay or weaken the checker.
""",
        public_fixture=CASES_ROOT / "attribute_nba_scoreboard" / "public",
        required_evidence=frozenset({"simulation", "waveform"}),
        grade=_attribution_grade,
    ),
    "systemverilog-signed-width": WorkflowCase(
        identifier="systemverilog-signed-width",
        prompt="""Diagnose and minimally repair the mixed-width signed saturating adder pipeline in this repository.
Preserve its ports, parameterization, synchronous reset, valid latency, rounding-free arithmetic, and supplied testbench.
Verify positive and negative saturation and signed-width boundaries with open-source tools; use equivalence only with an independently justified reference or properties.
This task requires bounded sequential equivalence through at least four rising edges: create a verification-only, independently structured mathematical reference under artifacts/ and record the result.
In the final response, state the root cause, exact file changed, evidence scopes, and any unverified boundary.
""",
        public_fixture=CASES_ROOT / "systemverilog_signed_width" / "public",
        required_evidence=frozenset({"lint", "simulation", "equivalence"}),
        grade=_signed_width_grade,
    ),
    "timing-refine-priority-path": WorkflowCase(
        identifier="timing-refine-priority-path",
        prompt="""Refine the measured priority-select timing path under the complete contract in SPEC.md.
Change only rtl/priority_select.v. Preserve its interface and exact combinational priority behavior; do not edit the testbench, cell models, Liberty, SDC, or add timing exceptions.
Record the real OpenSTA baseline, make one coherent topology change, and verify simulation, equivalence, synthesis, and final OpenSTA setup/hold closure with zero unconstrained endpoints.
Use only the supplied open-source inputs and tools. In the final response report the exact changed file, baseline/final metrics, evidence scope, and any remaining boundary.
""",
        public_fixture=CASES_ROOT / "timing_refine_priority_path" / "public",
        required_evidence=frozenset({"simulation", "equivalence", "synthesis", "sta"}),
        grade=_timing_grade,
    ),
    "waveform-first-divergence": WorkflowCase(
        identifier="waveform-first-divergence",
        prompt="""Analyze the supplied FST trace under the exact contract in SPEC.md.
Do not edit the RTL or trace. Use a bounded machine-readable FST divergence query, preserve its original-FST and conversion hashes, then create the exact diagnosis JSON requested by the specification.
In the final response report the first divergence time and values, the causal source behavior, the bounded window, and the original FST hash.
""",
        public_fixture=CASES_ROOT / "waveform_first_divergence" / "public",
        required_evidence=frozenset({"waveform"}),
        grade=_waveform_divergence_grade,
    ),
}


def get_case(identifier: str) -> WorkflowCase:
    try:
        return CASES[identifier]
    except KeyError as exc:
        raise ValueError(f"unknown workflow case: {identifier}") from exc
