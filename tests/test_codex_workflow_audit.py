from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from evals.run_codex_ab import (
    REASONING_EFFORTS,
    ResourcePolicy,
    TransportPolicy,
    _command_policy_findings,
    _current_passed_evidence_kinds,
    _disabled_host_skill_paths,
    _grade,
    _hash_tree,
    _monitor_resources,
    _network_infrastructure_failure,
    _open_tool_prefixes,
    _outer_bwrap_command,
    _paired_summary,
    _parse_trace,
    _prepare_workspace,
    _resource_command,
    _subprocess_text,
    _wilson_interval,
    _workflow_audit,
    _workspace_evidence,
)
from evals.workflow_cases import get_case
from rtl_ass.integrity import hash_file
from rtl_ass.waveform import query_waveform

ROOT = Path(__file__).resolve().parents[1]


class CodexWorkflowTraceTests(unittest.TestCase):
    def test_reasoning_effort_axis_covers_current_gpt_5_6_contract(self) -> None:
        self.assertEqual(REASONING_EFFORTS, ("none", "low", "medium", "high", "xhigh", "max"))

    def test_resource_monitor_reports_kernel_and_sampled_memory_peaks_separately(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            values = {
                "memory.current": "40\n",
                "memory.peak": "75\n",
                "memory.swap.current": "3\n",
                "pids.current": "6\n",
                "cpu.stat": "usage_usec 10\n",
                "memory.events": "oom 0\n",
            }
            for name, value in values.items():
                (root / name).write_text(value, encoding="utf-8")
            stop = mock.Mock()
            stop.is_set.side_effect = [False, False, True]
            state: dict[str, object] = {}
            telemetry = root / "telemetry.jsonl"
            with (
                mock.patch("evals.run_codex_ab._systemd_control_group", return_value=root),
                mock.patch("evals.run_codex_ab._host_available_memory", return_value=10_000),
            ):
                _monitor_resources(
                    unit="test-unit",
                    policy=ResourcePolicy(
                        memory_high_bytes=100,
                        memory_kill_bytes=200,
                        memory_max_bytes=300,
                        memory_swap_max_bytes=50,
                        host_available_kill_bytes=1,
                        sample_interval_seconds=0.01,
                    ),
                    telemetry_path=telemetry,
                    stop=stop,
                    state=state,
                )

            self.assertEqual(state["samples"], 1)
            self.assertEqual(
                state["peaks"],
                {
                    "memory_current_bytes": 40,
                    "memory_peak_bytes": 75,
                    "memory_swap_current_bytes": 3,
                    "pids_current": 6,
                },
            )
            sample = json.loads(telemetry.read_text(encoding="utf-8"))
            self.assertEqual(sample["memory_peak_bytes"], 75)

    def test_resource_policy_rejects_non_monotonic_memory_thresholds(self) -> None:
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            ResourcePolicy(memory_high_bytes=10, memory_kill_bytes=10, memory_max_bytes=20)

    def test_transport_policy_rejects_nonpositive_stall_threshold(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            TransportPolicy(network_stall_seconds=0)

    def test_resource_command_binds_cpu_memory_swap_and_process_limits(self) -> None:
        policy = ResourcePolicy(
            memory_high_bytes=10,
            memory_kill_bytes=15,
            memory_max_bytes=20,
            memory_swap_max_bytes=5,
            host_available_kill_bytes=30,
            cpu_quota_percent=200,
            tasks_max=40,
        )

        command = _resource_command(["/usr/bin/true"], "test-unit", policy, timeout=60)

        self.assertIn("--property=MemoryHigh=10", command)
        self.assertIn("--property=MemoryMax=20", command)
        self.assertIn("--property=MemorySwapMax=5", command)
        self.assertIn("--property=CPUQuota=200%", command)
        self.assertIn("--property=TasksMax=40", command)
        self.assertIn("--property=RuntimeMaxSec=120", command)
        self.assertEqual(command[:3], ["sudo", "-n", "systemd-run"])
        self.assertNotIn("--user", command)
        self.assertEqual(command[-2:], ["--", "/usr/bin/true"])

    def test_command_policy_detects_nested_network_vendor_and_agent_commands(self) -> None:
        findings = _command_policy_findings(
            '/bin/bash -lc "curl https://example.invalid; vivado -mode batch; python3 -m openai"'
        )

        self.assertEqual(
            findings,
            [
                {"reason": "network-command", "executable": "curl"},
                {"reason": "proprietary-tool-command", "executable": "vivado"},
                {"reason": "nested-agent-command", "executable": "python3"},
            ],
        )

    def test_command_policy_allows_cli_metadata_probes_but_rejects_agent_execution(self) -> None:
        self.assertEqual(_command_policy_findings("codex --help; openai --version; python3 -m openai -h"), [])
        self.assertEqual(
            _command_policy_findings("codex exec task; python3 -m openai responses create"),
            [
                {"reason": "nested-agent-command", "executable": "codex"},
                {"reason": "nested-agent-command", "executable": "python3"},
            ],
        )

    def test_workflow_audit_separates_policy_findings_from_correctness(self) -> None:
        case = get_case("waveform-first-divergence")
        trace = {
            "commands": [{"command": "yosys -p 'synth'", "status": "completed", "exit_code": 0}],
            "skill_signals": ["skill-file-read"],
            "invalid_jsonl_lines": 0,
            "executed_evidence_kinds": ["synthesis"],
        }

        audit = _workflow_audit(trace, case, "on", {"correct": True, "protected_files_unchanged": True})

        self.assertFalse(audit["compliant"])
        self.assertEqual(audit["executed_evidence_outside_case_policy"], ["synthesis"])
        self.assertEqual(audit["violations"], [])

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

    def test_terminal_network_error_is_infrastructure_but_recovered_error_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            trace = root / "trace.jsonl"
            trace.write_text(
                json.dumps({"type": "error", "message": "Connection failed: error sending request"}) + "\n",
                encoding="utf-8",
            )

            parsed = _parse_trace(trace, workspace)

        self.assertEqual(parsed["network_error_count"], 1)
        self.assertTrue(parsed["terminal_network_error"])
        self.assertTrue(_network_infrastructure_failure(parsed, return_code=255, timed_out=False))
        self.assertTrue(_network_infrastructure_failure(parsed, return_code=124, timed_out=True))
        self.assertFalse(_network_infrastructure_failure(parsed, return_code=0, timed_out=False))

    def test_codex_request_timeout_and_terminal_fallback_are_network_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            trace = root / "trace.jsonl"
            trace.write_text(
                "\n".join(
                    (
                        json.dumps({"type": "error", "message": "Reconnecting... 2/5 (request timed out)"}),
                        json.dumps(
                            {
                                "type": "item.completed",
                                "item": {
                                    "type": "error",
                                    "message": "Falling back from WebSockets to HTTPS transport. request timed out",
                                },
                            }
                        ),
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            parsed = _parse_trace(trace, workspace)

        self.assertEqual(parsed["network_error_count"], 2)
        self.assertTrue(parsed["terminal_network_error"])
        self.assertTrue(_network_infrastructure_failure(parsed, return_code=124, timed_out=True))

    def test_progress_after_network_error_clears_terminal_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            trace = root / "trace.jsonl"
            trace.write_text(
                "\n".join(
                    (
                        json.dumps({"type": "error", "message": "request timed out"}),
                        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}),
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            parsed = _parse_trace(trace, workspace)

        self.assertEqual(parsed["network_error_count"], 1)
        self.assertFalse(parsed["terminal_network_error"])
        self.assertFalse(_network_infrastructure_failure(parsed, return_code=124, timed_out=True))

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

    def test_skill_path_as_noop_argument_is_not_activation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            shutil.copytree(ROOT / ".agents" / "skills" / "rtl-ass", workspace / ".agents" / "skills" / "rtl-ass")
            trace = root / "trace.jsonl"
            event = {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": "true .agents/skills/rtl-ass/SKILL.md",
                    "status": "completed",
                    "exit_code": 0,
                },
            }
            trace.write_text(json.dumps(event) + "\n", encoding="utf-8")

            self.assertEqual(_parse_trace(trace, workspace)["skill_signals"], [])

    def test_ripgrep_read_and_direct_helper_execution_are_activation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            shutil.copytree(ROOT / ".agents" / "skills" / "rtl-ass", workspace / ".agents" / "skills" / "rtl-ass")
            trace = root / "trace.jsonl"
            events = [
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": "/bin/bash -lc \"rg -n 'verification' .agents/skills/rtl-ass/SKILL.md\"",
                        "status": "completed",
                        "exit_code": 0,
                    },
                },
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": ("/bin/bash -lc 'python3 .agents/skills/rtl-ass/scripts/rtl_ass.py --version'"),
                        "status": "completed",
                        "exit_code": 0,
                    },
                },
            ]
            trace.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

            self.assertEqual(_parse_trace(trace, workspace)["skill_signals"], ["helper-command", "skill-file-read"])

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

    def test_usage_is_complete_only_when_both_token_counts_are_present(self) -> None:
        def result(condition: str, usage: dict[str, int]) -> dict[str, object]:
            return {
                "replicate": 1,
                "condition": condition,
                "timed_out": False,
                "infrastructure_failure": False,
                "codex_return_code": 0,
                "duration_seconds": 1.0,
                "grade": {"correct": True},
                "trace": {"skill_signals": [], "executed_evidence_kinds": [], "usage": usage},
                "current_passed_evidence_kinds": [],
            }

        summary = _paired_summary(
            [
                result("off", {"input_tokens": 10}),
                result("on", {"input_tokens": 10, "output_tokens": 5}),
            ]
        )

        self.assertEqual(summary["conditions"]["off"]["usage_complete_runs"], 0)
        self.assertEqual(summary["conditions"]["off"]["input_tokens"], 10)
        self.assertIsNone(summary["conditions"]["off"]["output_tokens"])
        self.assertEqual(summary["conditions"]["on"]["usage_complete_runs"], 1)
        self.assertEqual(summary["conditions"]["on"]["input_tokens"], 10)
        self.assertEqual(summary["conditions"]["on"]["output_tokens"], 5)

    def test_evidence_completeness_requires_current_candidate_and_supplied_testbench(self) -> None:
        def record(kind: str, status: str, hashes: list[str]) -> dict[str, object]:
            return {
                "kind": kind,
                "status": status,
                "strictly_valid": True,
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
    def test_outer_bwrap_mounts_only_explicit_payloads_and_drops_agent_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "codex"
            launcher = package / "bin" / "codex.js"
            native = package / "node_modules" / "@openai" / "codex-linux-x64" / "vendor" / "x86_64" / "bin" / "codex"
            workspace = root / "public" / "workspace"
            codex_home = root / "auth-home"
            temporary_directory = workspace.parent / "tmp"
            for path in (launcher, native):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("#!/bin/sh\n", encoding="utf-8")
                path.chmod(0o755)
            (package / "package.json").write_text("{}\n", encoding="utf-8")
            workspace.mkdir(parents=True)
            codex_home.mkdir()
            temporary_directory.mkdir()

            with mock.patch("evals.run_codex_ab._open_tool_prefixes", return_value={}):
                command, mounts = _outer_bwrap_command(
                    executable=launcher.as_posix(),
                    workspace=workspace,
                    codex_home=codex_home,
                    temporary_directory=temporary_directory,
                    model="test-model",
                    effort="low",
                    prompt="test prompt",
                )

        self.assertIn("--unshare-pid", command)
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
        self.assertIn("--bounding-set=-all", command)
        self.assertNotIn("sudo", command)
        self.assertIn("/run/systemd/resolve/stub-resolv.conf", command)
        self.assertNotIn("--ro-bind", command[-20:])
        self.assertEqual(
            [item for item in mounts if item["mode"] == "read-write"],
            [
                {"source": workspace.as_posix(), "target": workspace.as_posix(), "mode": "read-write"},
                {"source": codex_home.as_posix(), "target": "/opt/rtl-ass-home/.codex", "mode": "read-write"},
                {"source": temporary_directory.as_posix(), "target": "/tmp", "mode": "read-write"},
            ],
        )
        self.assertIn("TMPDIR", command)
        self.assertIn(f"--reuid={os.getuid()}", command)
        self.assertIn(f"--regid={os.getgid()}", command)
        self.assertFalse(any(Path.home().as_posix() in value for value in command))
        self.assertFalse(any("private" in item["source"] for item in mounts))

    def test_open_tool_prefixes_are_derived_from_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary) / "tool-prefix"
            executable = prefix / "bin" / "yosys"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
            with mock.patch.dict(os.environ, {"PATH": executable.parent.as_posix()}):
                prefixes = _open_tool_prefixes()

        self.assertEqual(prefixes, {"yosys": prefix})

    def test_release_skill_payload_uses_embedded_runtime_without_source_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "released-skill"
            (skill / "scripts").mkdir(parents=True)
            (skill / "runtime").mkdir()
            (skill / "SKILL.md").write_text("---\nname: rtl-ass\n---\n", encoding="utf-8")
            (skill / "scripts" / "rtl_ass.py").write_text("pass\n", encoding="utf-8")
            (skill / "runtime" / "runtime.whl").write_bytes(b"wheel")
            workspace = root / "workspace"

            _prepare_workspace(workspace, "on", skill_root=skill)

            self.assertTrue((workspace / ".agents" / "skills" / "rtl-ass" / "runtime" / "runtime.whl").is_file())
            self.assertFalse((workspace / "src" / "rtl_ass").exists())
            self.assertFalse((workspace / "pyproject.toml").exists())

    def test_host_skill_exclusions_keep_system_skills_and_disable_rtl_or_plugin_skills(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            user_skill = root / "skills" / "rtl-helper" / "SKILL.md"
            system_skill = root / "skills" / ".system" / "skill-creator" / "SKILL.md"
            plugin_skill = root / "plugins" / "cache" / "vendor" / "skill" / "SKILL.md"
            for path in (user_skill, system_skill, plugin_skill):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("---\nname: test\n---\n", encoding="utf-8")

            exclusions = _disabled_host_skill_paths(root)

        self.assertIn(user_skill.resolve(), exclusions)
        self.assertIn(plugin_skill.resolve(), exclusions)
        self.assertIn((ROOT / ".agents" / "skills" / "rtl-ass" / "SKILL.md").resolve(), exclusions)
        self.assertNotIn(system_skill.resolve(), exclusions)

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

    def test_forged_wave_query_json_is_not_structured_waveform_evidence(self) -> None:
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

            self.assertEqual(kinds, [])

    def test_forged_fst_divergence_json_is_not_structured_waveform_evidence(self) -> None:
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

            self.assertEqual(kinds, [])

    def test_real_current_wave_query_is_structured_waveform_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            artifact_dir = workspace / "artifacts"
            artifact_dir.mkdir()
            waveform = artifact_dir / "divergence.vcd"
            shutil.copy2(ROOT / "tests" / "fixtures" / "divergence.vcd", waveform)
            result = query_waveform(waveform, patterns=("tb.actual",))
            artifact = artifact_dir / "wave-query.json"
            artifact.write_text(json.dumps(result) + "\n", encoding="utf-8")

            records = _workspace_evidence(workspace)
            kinds = _current_passed_evidence_kinds(
                records,
                expected_subjects={"waveform": [hash_file(waveform)]},
            )

            self.assertEqual(kinds, ["waveform"])

    def test_minimal_forged_run_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            artifact = workspace / "artifacts" / "run-evidence.json"
            artifact.parent.mkdir()
            artifact.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "kind": "lint",
                        "status": "pass",
                        "subject_hashes": [{"content_hash": "a" * 64}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            records = _workspace_evidence(workspace)

            self.assertFalse(records[0]["strictly_valid"])
            self.assertEqual(records[0]["reason"], "invalid_evidence")

    def test_current_relative_subject_and_artifact_paths_validate_from_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            subject = workspace / "rtl" / "dut.sv"
            artifact = workspace / "artifacts" / "stdout.log"
            evidence_file = workspace / "artifacts" / "run-evidence.json"
            subject.parent.mkdir()
            artifact.parent.mkdir()
            subject.write_text("module dut; endmodule\n", encoding="utf-8")
            artifact.write_text("PASS\n", encoding="utf-8")
            evidence = {
                "schema_version": "1.0",
                "kind": "lint",
                "status": "pass",
                "tool": {"name": "verilator", "version": "test"},
                "input_hash": "a" * 64,
                "subject_hashes": [{"index": 0, "path": "rtl/dut.sv", "content_hash": hash_file(subject)}],
                "commands": [["verilator", "--lint-only", "rtl/dut.sv"]],
                "artifacts": ["artifacts/stdout.log"],
                "artifact_hashes": [{"index": 0, "path": "artifacts/stdout.log", "content_hash": hash_file(artifact)}],
                "top": "dut",
                "claim_scope": "tool execution evidence only",
                "evidence_file": "artifacts/run-evidence.json",
                "started_at": "2026-09-01T00:00:00+00:00",
                "finished_at": "2026-09-01T00:00:01+00:00",
                "summary": {"returncode": 0},
            }
            evidence_file.write_text(json.dumps(evidence) + "\n", encoding="utf-8")

            records = _workspace_evidence(workspace)

            self.assertTrue(records[0]["strictly_valid"])
            self.assertIsNone(records[0]["reason"])


if __name__ == "__main__":
    unittest.main()
