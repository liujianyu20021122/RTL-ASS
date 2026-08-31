from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from evals.run_codex_ab import (
    _current_passed_evidence_kinds,
    _grade,
    _hash_tree,
    _paired_summary,
    _parse_trace,
    _prepare_workspace,
    _subprocess_text,
    _wilson_interval,
    _workspace_evidence,
)

ROOT = Path(__file__).resolve().parents[1]


class CodexWorkflowTraceTests(unittest.TestCase):
    def test_wilson_interval_is_bounded_and_handles_empty_samples(self) -> None:
        self.assertIsNone(_wilson_interval(0, 0))
        self.assertEqual(_wilson_interval(5, 5), [0.565518, 1.0])
        lower, upper = _wilson_interval(2, 5) or (-1.0, -1.0)
        self.assertLess(lower, 0.4)
        self.assertGreater(upper, 0.4)

    def test_timeout_partial_output_is_preserved(self) -> None:
        self.assertEqual(_subprocess_text(b'{"type":"turn.started"}\n'), '{"type":"turn.started"}\n')
        self.assertEqual(_subprocess_text(None), "")

    def test_sanitizer_keeps_observable_events_and_drops_reasoning_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            shutil.copytree(ROOT / ".agents" / "skills" / "rtl-ass", workspace / ".agents" / "skills" / "rtl-ass")
            trace = root / "trace.jsonl"
            events = [
                {"type": "thread.started", "thread_id": "private-thread-id"},
                {"type": "item.completed", "item": {"type": "reasoning", "text": "private reasoning"}},
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": f"sed -n '1,80p' {workspace}/.agents/skills/rtl-ass/SKILL.md",
                        "status": "completed",
                        "exit_code": 0,
                    },
                },
                {
                    "type": "item.completed",
                    "item": {
                        "type": "file_change",
                        "changes": [{"path": f"{workspace}/rtl/dut.sv", "kind": "update"}],
                        "status": "completed",
                    },
                },
                {"type": "item.completed", "item": {"type": "agent_message", "text": "repair complete"}},
                {"type": "turn.completed", "usage": {"input_tokens": 11, "output_tokens": 7}},
            ]
            trace.write_text("\n".join(json.dumps(item) for item in events) + "\n", encoding="utf-8")

            parsed = _parse_trace(trace, workspace)

            self.assertFalse(parsed["reasoning_content_retained"])
            self.assertNotIn("private reasoning", json.dumps(parsed))
            self.assertNotIn("private-thread-id", json.dumps(parsed))
            self.assertEqual(parsed["skill_signals"], ["skill-file-read"])
            self.assertEqual(parsed["file_changes"], [{"path": "$WORKSPACE/rtl/dut.sv", "kind": "update"}])
            self.assertEqual(parsed["usage"], {"input_tokens": 11, "output_tokens": 7})

    def test_unrelated_global_skill_read_is_not_rtl_ass_activation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            trace = root / "trace.jsonl"
            event = {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": "sed -n '1,80p' /opt/codex/skills/other/SKILL.md",
                    "status": "completed",
                    "exit_code": 0,
                },
            }
            trace.write_text(json.dumps(event) + "\n", encoding="utf-8")

            self.assertEqual(_parse_trace(trace, workspace)["skill_signals"], [])

    def test_failed_repository_skill_read_is_not_activation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            trace = root / "trace.jsonl"
            event = {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": "sed -n '1,80p' .agents/skills/rtl-ass/SKILL.md",
                    "status": "failed",
                    "exit_code": 2,
                },
            }
            trace.write_text(json.dumps(event) + "\n", encoding="utf-8")

            self.assertEqual(_parse_trace(trace, workspace)["skill_signals"], [])

    def test_successful_module_probe_is_not_rtl_ass_activation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            trace = root / "trace.jsonl"
            event = {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": (
                        "python3 -m rtl_ass --help 2>/dev/null; "
                        "python3 -m rtl_assist --help 2>/dev/null; "
                        "python3 -m wave --help 2>/dev/null | sed -n '1,20p'"
                    ),
                    "status": "completed",
                    "exit_code": 0,
                },
            }
            trace.write_text(json.dumps(event) + "\n", encoding="utf-8")

            self.assertEqual(_parse_trace(trace, workspace)["skill_signals"], [])

    def test_invalid_pairs_do_not_enter_correctness_denominator(self) -> None:
        def result(condition: str, *, correct: bool, infrastructure_failure: bool) -> dict[str, object]:
            return {
                "replicate": 1,
                "condition": condition,
                "timed_out": False,
                "infrastructure_failure": infrastructure_failure,
                "codex_return_code": 0,
                "duration_seconds": 1.0,
                "grade": {"correct": correct},
                "trace": {
                    "skill_signals": ["invalid-signal"] if infrastructure_failure else [],
                    "executed_evidence_kinds": ["lint", "simulation", "synthesis"],
                    "usage": {"input_tokens": 999, "output_tokens": 111},
                },
                "current_passed_evidence_kinds": ["lint", "simulation", "synthesis"],
            }

        summary = _paired_summary(
            [
                result("off", correct=True, infrastructure_failure=True),
                result("on", correct=True, infrastructure_failure=False),
            ]
        )

        self.assertEqual(summary["conditions"]["off"]["valid_runs"], 0)
        self.assertIsNone(summary["conditions"]["off"]["task_success_rate"])
        self.assertEqual(summary["conditions"]["off"]["observed_skill_use"], 0)
        self.assertEqual(summary["conditions"]["off"]["complete_structured_evidence"], 0)
        self.assertEqual(summary["conditions"]["off"]["input_tokens"], 0)
        self.assertFalse(summary["paired_outcomes"][0]["valid"])

    def test_timeout_is_a_valid_task_failure_but_preserves_candidate_correctness(self) -> None:
        def result(condition: str, *, timed_out: bool) -> dict[str, object]:
            return {
                "replicate": 1,
                "condition": condition,
                "timed_out": timed_out,
                "infrastructure_failure": False,
                "codex_return_code": 124 if timed_out else 0,
                "duration_seconds": 10.0,
                "grade": {"correct": True},
                "trace": {"skill_signals": [], "executed_evidence_kinds": [], "usage": {}},
                "current_passed_evidence_kinds": [],
            }

        summary = _paired_summary([result("off", timed_out=False), result("on", timed_out=True)])

        self.assertEqual(summary["conditions"]["on"]["valid_runs"], 1)
        self.assertEqual(summary["conditions"]["on"]["task_successes"], 0)
        self.assertEqual(summary["conditions"]["on"]["candidate_correct"], 1)
        self.assertEqual(summary["conditions"]["on"]["timeouts"], 1)
        self.assertEqual(summary["paired_comparisons"]["off_only_success"], 1)

    def test_task_success_requires_explicit_deliverable_completeness_when_present(self) -> None:
        def result(condition: str, *, complete: bool) -> dict[str, object]:
            return {
                "replicate": 1,
                "condition": condition,
                "timed_out": False,
                "infrastructure_failure": False,
                "codex_return_code": 0,
                "duration_seconds": 1.0,
                "grade": {"correct": True, "complete": complete},
                "trace": {"skill_signals": [], "executed_evidence_kinds": [], "usage": {}},
                "current_passed_evidence_kinds": [],
            }

        summary = _paired_summary([result("off", complete=False), result("on", complete=True)])

        self.assertEqual(summary["conditions"]["off"]["candidate_correct"], 1)
        self.assertEqual(summary["conditions"]["off"]["deliverable_complete"], 0)
        self.assertEqual(summary["conditions"]["off"]["task_successes"], 0)
        self.assertEqual(summary["conditions"]["on"]["deliverable_complete"], 1)
        self.assertEqual(summary["conditions"]["on"]["task_successes"], 1)

    def test_evidence_completeness_requires_current_candidate_and_supplied_testbench(self) -> None:
        def record(kind: str, status: str, hashes: list[str]) -> dict[str, object]:
            return {
                "kind": kind,
                "status": status,
                "subject_hashes": [{"content_hash": item} for item in hashes],
            }

        kinds = _current_passed_evidence_kinds(
            [
                record("lint", "pass", ["candidate"]),
                record("synthesis", "pass", ["stale-candidate"]),
                record("simulation", "pass", ["candidate"]),
                record("formal", "fail", ["candidate", "testbench"]),
                record("simulation", "pass", ["candidate", "testbench"]),
            ],
            expected_subjects={
                "lint": ["candidate"],
                "simulation": ["candidate", "testbench"],
                "synthesis": ["candidate"],
            },
        )

        self.assertEqual(kinds, ["lint", "simulation"])


class CodexWorkflowFixtureTests(unittest.TestCase):
    def test_on_workspace_contains_local_runtime_while_off_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            off_workspace = root / "off"
            on_workspace = root / "on"

            _prepare_workspace(off_workspace, "off")
            _prepare_workspace(on_workspace, "on")

            self.assertFalse((off_workspace / "src" / "rtl_ass").exists())
            self.assertFalse((off_workspace / ".agents" / "skills" / "rtl-ass").exists())
            self.assertTrue((on_workspace / "src" / "rtl_ass" / "cli.py").is_file())
            self.assertTrue((on_workspace / ".agents" / "skills" / "rtl-ass" / "SKILL.md").is_file())
            self.assertEqual(list((on_workspace / "src" / "rtl_ass").rglob("*.pyc")), [])
            self.assertEqual(list((on_workspace / "src" / "rtl_ass").rglob("__pycache__")), [])
            self.assertEqual(list((on_workspace / ".agents" / "skills" / "rtl-ass").rglob("*.pyc")), [])
            self.assertEqual(list((on_workspace / ".agents" / "skills" / "rtl-ass").rglob("__pycache__")), [])
            self.assertEqual(_hash_tree(ROOT / "src" / "rtl_ass"), _hash_tree(on_workspace / "src" / "rtl_ass"))
            self.assertEqual(
                _hash_tree(ROOT / ".agents" / "skills" / "rtl-ass"),
                _hash_tree(on_workspace / ".agents" / "skills" / "rtl-ass"),
            )

    def test_runtime_tree_hash_ignores_bytecode_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
            baseline = _hash_tree(root)
            cache = root / "__pycache__"
            cache.mkdir()
            (cache / "module.cpython-312.pyc").write_bytes(b"non-reproducible-bytecode")
            (root / "ignored.pyc").write_bytes(b"more-bytecode")
            (root / "module-link.py").symlink_to(root / "module.py")

            self.assertEqual(_hash_tree(root), baseline)

    def test_hidden_grader_rejects_fixture_and_accepts_minimal_wrap_fix(self) -> None:
        if not all(shutil.which(tool) for tool in ("iverilog", "vvp", "verilator", "yosys")):
            self.skipTest("open RTL grader tools are unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            initial = _prepare_workspace(workspace, "off")

            baseline = _grade(workspace, root / "baseline", initial)
            self.assertFalse(baseline["correct"])
            self.assertEqual(baseline["grader_statuses"]["simulation"], "fail")

            candidate = workspace / "rtl" / "sync_fifo.sv"
            source = candidate.read_text(encoding="utf-8")
            source = source.replace(
                "write_ptr      <= write_ptr + 1'b1;",
                "write_ptr      <= (write_ptr == PTR_W'(DEPTH - 1)) ? '0 : write_ptr + 1'b1;",
            ).replace(
                "read_ptr <= read_ptr + 1'b1;",
                "read_ptr <= (read_ptr == PTR_W'(DEPTH - 1)) ? '0 : read_ptr + 1'b1;",
            )
            candidate.write_text(source, encoding="utf-8")

            repaired = _grade(workspace, root / "repaired", initial)
            self.assertTrue(repaired["correct"])
            self.assertTrue(repaired["source_changed"])
            self.assertTrue(repaired["protected_files_unchanged"])

    def test_external_grader_rejects_a_missing_candidate_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            initial = _prepare_workspace(workspace, "off")
            (workspace / "rtl" / "sync_fifo.sv").unlink()

            grade = _grade(workspace, root / "grade", initial)

            self.assertFalse(grade["correct"])
            self.assertEqual(grade["error"], "candidate_not_regular_file")

    def test_agent_evidence_symlink_is_not_followed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            evidence_dir = workspace / "artifacts"
            evidence_dir.mkdir(parents=True)
            outside = root / "outside.json"
            outside.write_text('{"kind":"lint","status":"pass"}\n', encoding="utf-8")
            (evidence_dir / "run-evidence.json").symlink_to(outside)

            records = _workspace_evidence(workspace)

            self.assertEqual(
                records,
                [
                    {
                        "path": "artifacts/run-evidence.json",
                        "valid_json": False,
                        "reason": "symlink_not_allowed",
                    }
                ],
            )

    def test_completed_wave_query_json_is_structured_waveform_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            artifact = workspace / "artifacts" / "wave-query.json"
            artifact.parent.mkdir()
            artifact.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "kind": "vcd-query",
                        "status": "complete",
                        "waveform": "artifacts/failure.vcd",
                        "waveform_hash": "a" * 64,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            records = _workspace_evidence(workspace)
            kinds = _current_passed_evidence_kinds(records, expected_subjects={"waveform": []})

            self.assertEqual(kinds, ["waveform"])

    def test_found_fst_divergence_json_is_structured_waveform_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            artifact = workspace / "artifacts" / "wave-divergence.json"
            artifact.parent.mkdir()
            artifact.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "kind": "fst-first-divergence",
                        "status": "found",
                        "waveform": "artifacts/failure.fst",
                        "waveform_hash": "b" * 64,
                        "first_divergence": {"time": 20},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            records = _workspace_evidence(workspace)
            kinds = _current_passed_evidence_kinds(records, expected_subjects={"waveform": []})

            self.assertEqual(kinds, ["waveform"])


if __name__ == "__main__":
    unittest.main()
