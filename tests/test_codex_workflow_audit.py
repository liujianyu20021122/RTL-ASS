from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from evals.run_codex_ab import (
    _current_passed_evidence_kinds,
    _grade,
    _paired_summary,
    _parse_trace,
    _prepare_workspace,
    _subprocess_text,
    _workspace_evidence,
)


class CodexWorkflowTraceTests(unittest.TestCase):
    def test_timeout_partial_output_is_preserved(self) -> None:
        self.assertEqual(_subprocess_text(b'{"type":"turn.started"}\n'), '{"type":"turn.started"}\n')
        self.assertEqual(_subprocess_text(None), "")

    def test_sanitizer_keeps_observable_events_and_drops_reasoning_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
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
                    "skill_signals": [],
                    "executed_evidence_kinds": [],
                    "usage": {},
                },
                "current_passed_evidence_kinds": [],
            }

        summary = _paired_summary(
            [
                result("off", correct=True, infrastructure_failure=True),
                result("on", correct=True, infrastructure_failure=False),
            ]
        )

        self.assertEqual(summary["conditions"]["off"]["valid_runs"], 0)
        self.assertIsNone(summary["conditions"]["off"]["task_success_rate"])
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
            candidate_hash="candidate",
            visible_testbench_hash="testbench",
        )

        self.assertEqual(kinds, ["lint", "simulation"])


class CodexWorkflowFixtureTests(unittest.TestCase):
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
            self.assertTrue(repaired["visible_testbench_unchanged"])

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


if __name__ == "__main__":
    unittest.main()
