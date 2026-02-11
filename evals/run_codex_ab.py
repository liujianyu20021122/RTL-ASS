#!/usr/bin/env python3
"""Run isolated, paired Codex workflow audits with and without RTL-ASS."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from rtl_ass.evidence import run_iverilog_simulation, run_verilator_lint, run_yosys_synthesis
from rtl_ass.integrity import canonical_json, hash_file
from rtl_ass.tools import discover_tools

ROOT = Path(__file__).resolve().parents[1]
CASE_ROOT = ROOT / "evals" / "workflow_cases" / "non_power_two_fifo"
PUBLIC_FIXTURE = CASE_ROOT / "public"
HIDDEN_TESTBENCH = CASE_ROOT / "private" / "sync_fifo_hidden_tb.sv"
SKILL_ROOT = ROOT / ".agents" / "skills" / "rtl-ass"
PROMPT = """Diagnose and minimally repair the depth-three synchronous FIFO in this repository.
Preserve its module interface, reset behavior, externally visible latency, parameterization, and test intent.
Do not weaken or rewrite the supplied testbench. Run the strongest relevant open-source verification available.
In the final response, state the root cause, exact files changed, and executed evidence with its scope.
"""
AGENT_RULES = """# Evaluation workspace

Repair only the supplied RTL task. Do not access files outside this repository.
Preserve the interface and latency contract, do not weaken tests, and use only open-source tools.
Generated evidence may be written under artifacts/. Do not commit changes.
"""
REQUIRED_EVIDENCE = frozenset({"lint", "simulation", "synthesis"})


def _hash_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _run(command: list[str], *, cwd: Path, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _subprocess_text(value: str | bytes | None) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return ""


def _prepare_workspace(workspace: Path, condition: str) -> dict[str, str]:
    if workspace.exists():
        raise RuntimeError(f"refusing to reuse evaluation workspace: {workspace}")
    shutil.copytree(PUBLIC_FIXTURE, workspace)
    (workspace / "AGENTS.md").write_text(AGENT_RULES, encoding="utf-8")
    if condition == "on":
        destination = workspace / ".agents" / "skills" / "rtl-ass"
        destination.parent.mkdir(parents=True)
        shutil.copytree(SKILL_ROOT, destination)
    commands = (
        ["git", "init", "-b", "main"],
        ["git", "config", "user.name", "RTL-ASS Eval"],
        ["git", "config", "user.email", "eval@example.invalid"],
        ["git", "add", "."],
        ["git", "commit", "-m", "evaluation fixture"],
    )
    for command in commands:
        result = _run(command, cwd=workspace)
        if result.returncode != 0:
            raise RuntimeError(f"workspace setup failed: {command}: {result.stderr.strip()}")
    return {
        "rtl_hash": hash_file(workspace / "rtl" / "sync_fifo.sv"),
        "testbench_hash": hash_file(workspace / "tb" / "sync_fifo_visible_tb.sv"),
        "repository_head": _run(["git", "rev-parse", "HEAD"], cwd=workspace).stdout.strip(),
    }


def _redact(text: str, workspace: Path) -> str:
    replacements = (
        (workspace.as_posix(), "$WORKSPACE"),
        (ROOT.as_posix(), "$RTL_ASS_ROOT"),
        (Path.home().as_posix(), "$HOME"),
    )
    result = text
    for source, replacement in replacements:
        result = result.replace(source, replacement)
    return result


def _command_kinds(command: str) -> set[str]:
    lowered = command.lower()
    kinds: set[str] = set()
    if "verilator" in lowered or "verify lint" in lowered:
        kinds.add("lint")
    if "iverilog" in lowered or " vvp" in lowered or "verify simulate" in lowered:
        kinds.add("simulation")
    if "verify formal" in lowered or ("yosys" in lowered and "sat" in lowered):
        kinds.add("formal")
    if "verify synth" in lowered or ("yosys" in lowered and "synth" in lowered):
        kinds.add("synthesis")
    return kinds


def _parse_trace(path: Path, workspace: Path) -> dict[str, Any]:
    event_counts: Counter[str] = Counter()
    item_counts: Counter[str] = Counter()
    commands: list[dict[str, Any]] = []
    file_changes: list[dict[str, Any]] = []
    final_messages: list[str] = []
    usage: dict[str, Any] = {}
    thread_ids: list[str] = []
    executed_kinds: set[str] = set()
    skill_signals: set[str] = set()
    invalid_lines = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            invalid_lines += 1
            continue
        event_type = event.get("type")
        if isinstance(event_type, str):
            event_counts[event_type] += 1
        if event_type == "thread.started" and isinstance(event.get("thread_id"), str):
            thread_ids.append(hashlib.sha256(event["thread_id"].encode()).hexdigest())
        if event_type == "turn.completed" and isinstance(event.get("usage"), dict):
            usage = event["usage"]
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if isinstance(item_type, str):
            item_counts[item_type] += 1
        if item_type == "reasoning":
            continue
        if item_type == "agent_message" and isinstance(item.get("text"), str):
            final_messages.append(_redact(item["text"], workspace))
        if item_type == "file_change" and event_type == "item.completed":
            changes = item.get("changes")
            if isinstance(changes, list):
                for change in changes:
                    if not isinstance(change, dict) or not isinstance(change.get("path"), str):
                        continue
                    file_changes.append(
                        {
                            "path": _redact(change["path"], workspace),
                            "kind": change.get("kind"),
                        }
                    )
        if item_type != "command_execution" or event_type != "item.completed":
            continue
        command = item.get("command")
        if not isinstance(command, str):
            continue
        redacted = _redact(command, workspace)
        exit_code = item.get("exit_code")
        commands.append(
            {
                "command": redacted,
                "status": item.get("status"),
                "exit_code": exit_code if isinstance(exit_code, int) else None,
            }
        )
        command_succeeded = item.get("status") == "completed" and exit_code == 0
        if command_succeeded:
            executed_kinds.update(_command_kinds(command))
            if ".agents/skills/rtl-ass/scripts/rtl_ass.py" in command or "python3 -m rtl_ass" in command:
                skill_signals.add("helper-command")
            if ".agents/skills/rtl-ass/SKILL.md" in command or ".agents/skills/rtl-ass/references" in command:
                skill_signals.add("skill-file-read")
    return {
        "event_counts": dict(sorted(event_counts.items())),
        "item_counts": dict(sorted(item_counts.items())),
        "reasoning_content_retained": False,
        "invalid_jsonl_lines": invalid_lines,
        "thread_id_hashes": thread_ids,
        "commands": commands,
        "file_changes": file_changes,
        "executed_evidence_kinds": sorted(executed_kinds),
        "skill_signals": sorted(skill_signals),
        "agent_messages": final_messages,
        "usage": usage,
    }


def _workspace_evidence(workspace: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(workspace.rglob("run-evidence.json")):
        if path.is_symlink():
            records.append(
                {
                    "path": path.relative_to(workspace).as_posix(),
                    "valid_json": False,
                    "reason": "symlink_not_allowed",
                }
            )
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            records.append({"path": path.relative_to(workspace).as_posix(), "valid_json": False})
            continue
        raw_subjects = value.get("subject_hashes") if isinstance(value, dict) else None
        subjects = []
        if isinstance(raw_subjects, list):
            for subject in raw_subjects:
                if not isinstance(subject, dict):
                    continue
                subject_path = subject.get("path")
                subjects.append(
                    {
                        "index": subject.get("index"),
                        "path": _redact(subject_path, workspace) if isinstance(subject_path, str) else None,
                        "content_hash": subject.get("content_hash"),
                    }
                )
        records.append(
            {
                "path": path.relative_to(workspace).as_posix(),
                "valid_json": isinstance(value, dict),
                "kind": value.get("kind") if isinstance(value, dict) else None,
                "status": value.get("status") if isinstance(value, dict) else None,
                "input_hash": value.get("input_hash") if isinstance(value, dict) else None,
                "top": value.get("top") if isinstance(value, dict) else None,
                "subject_hashes": subjects,
                "file_hash": hash_file(path),
            }
        )
    return records


def _current_passed_evidence_kinds(
    records: Iterable[dict[str, Any]], *, candidate_hash: str, visible_testbench_hash: str
) -> list[str]:
    kinds: set[str] = set()
    for record in records:
        kind = record.get("kind")
        if record.get("status") != "pass" or not isinstance(kind, str):
            continue
        subject_hashes = {
            subject.get("content_hash")
            for subject in record.get("subject_hashes", [])
            if isinstance(subject, dict) and isinstance(subject.get("content_hash"), str)
        }
        if candidate_hash not in subject_hashes:
            continue
        if kind == "simulation" and visible_testbench_hash not in subject_hashes:
            continue
        kinds.add(kind)
    return sorted(kinds)


def _grade(workspace: Path, run_root: Path, initial: dict[str, str]) -> dict[str, Any]:
    candidate = workspace / "rtl" / "sync_fifo.sv"
    visible_testbench = workspace / "tb" / "sync_fifo_visible_tb.sv"
    evidence_root = run_root / "grader-evidence"
    if not candidate.is_file() or candidate.is_symlink():
        return {"correct": False, "error": "candidate_not_regular_file"}
    lint = run_verilator_lint([candidate], top="sync_fifo", artifact_root=evidence_root)
    simulation = run_iverilog_simulation(
        [candidate, HIDDEN_TESTBENCH],
        top="sync_fifo_hidden_tb",
        artifact_root=evidence_root,
    )
    synthesis = run_yosys_synthesis([candidate], top="sync_fifo", artifact_root=evidence_root)
    changed = _run(["git", "diff", "--name-only", "HEAD"], cwd=workspace)
    status = _run(["git", "status", "--short"], cwd=workspace)
    visible_hash = (
        hash_file(visible_testbench) if visible_testbench.is_file() and not visible_testbench.is_symlink() else None
    )
    statuses = {item["kind"]: item["status"] for item in (lint, simulation, synthesis)}
    candidate_hash = hash_file(candidate)
    source_changed = candidate_hash != initial["rtl_hash"]
    visible_testbench_unchanged = visible_hash == initial["testbench_hash"]
    tracked_changed_files = [line for line in changed.stdout.splitlines() if line]
    return {
        "correct": (
            all(statuses.get(kind) == "pass" for kind in REQUIRED_EVIDENCE)
            and source_changed
            and visible_testbench_unchanged
            and tracked_changed_files == ["rtl/sync_fifo.sv"]
        ),
        "grader_statuses": statuses,
        "candidate_hash": candidate_hash,
        "source_changed": source_changed,
        "visible_testbench_unchanged": visible_testbench_unchanged,
        "tracked_changed_files": tracked_changed_files,
        "git_status": status.stdout.splitlines(),
        "evidence": [
            {
                "kind": item["kind"],
                "status": item["status"],
                "input_hash": item["input_hash"],
                "evidence_file_hash": (
                    hash_file(item["evidence_file"])
                    if isinstance(item.get("evidence_file"), str) and Path(item["evidence_file"]).is_file()
                    else None
                ),
            }
            for item in (lint, simulation, synthesis)
        ],
    }


def _codex_version(executable: str) -> str:
    result = subprocess.run([executable, "--version"], check=False, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"cannot execute Codex: {result.stderr.strip()}")
    return result.stdout.strip()


def _run_one(
    *,
    executable: str,
    model: str,
    effort: str,
    sandbox: str,
    timeout: int,
    output: Path,
    replicate: int,
    condition: str,
) -> dict[str, Any]:
    run_id = f"pair-{replicate:02d}-{condition}"
    run_root = output / "runs" / run_id
    workspace = run_root / "workspace"
    run_root.mkdir(parents=True)
    initial = _prepare_workspace(workspace, condition)
    trace_path = run_root / "trace.raw.jsonl"
    stderr_path = run_root / "codex.stderr.txt"
    command = [
        executable,
        "exec",
        "--ephemeral",
        "--json",
        "--ignore-user-config",
        "--sandbox",
        sandbox,
        "--model",
        model,
        "-c",
        f'model_reasoning_effort="{effort}"',
        "-C",
        str(workspace),
        PROMPT,
    ]
    environment = os.environ.copy()
    original_codex_home = Path(environment.get("CODEX_HOME", Path.home() / ".codex"))
    isolated_codex_home = run_root / "codex-home"
    isolated_codex_home.mkdir()
    auth_source = original_codex_home / "auth.json"
    if auth_source.is_file():
        shutil.copy2(auth_source, isolated_codex_home / "auth.json")
    elif "CODEX_API_KEY" not in environment:
        raise RuntimeError("Codex authentication is unavailable for the isolated evaluation home")
    environment["CODEX_HOME"] = str(isolated_codex_home)
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = str(ROOT / "src") + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    started_at = datetime.now(UTC).isoformat()
    started_monotonic = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=environment,
        )
        return_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        return_code = 124
        stdout = _subprocess_text(exc.stdout)
        stderr = _subprocess_text(exc.stderr)
    finally:
        shutil.rmtree(isolated_codex_home)
    finished_at = datetime.now(UTC).isoformat()
    duration_seconds = round(time.monotonic() - started_monotonic, 3)
    trace_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(_redact(stderr, workspace), encoding="utf-8")
    trace = _parse_trace(trace_path, workspace)
    observable_text = "\n".join(trace["agent_messages"]) + "\n" + stderr
    infrastructure_failure = any(
        marker in observable_text for marker in ("Failed RTM_NEWADDR", "sandbox failure", "execution sandbox", "bwrap:")
    )
    agent_evidence = _workspace_evidence(workspace)
    grade = _grade(workspace, run_root, initial)
    candidate_hash = grade.get("candidate_hash")
    visible_testbench = workspace / "tb" / "sync_fifo_visible_tb.sv"
    if isinstance(candidate_hash, str) and visible_testbench.is_file() and not visible_testbench.is_symlink():
        current_passed_evidence_kinds = _current_passed_evidence_kinds(
            agent_evidence,
            candidate_hash=candidate_hash,
            visible_testbench_hash=hash_file(visible_testbench),
        )
    else:
        current_passed_evidence_kinds = []
    result = {
        "schema_version": "1.0",
        "run_id": run_id,
        "replicate": replicate,
        "condition": condition,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": duration_seconds,
        "codex_return_code": return_code,
        "timed_out": timed_out,
        "infrastructure_failure": infrastructure_failure,
        "initial": initial,
        "trace": trace,
        "agent_evidence": agent_evidence,
        "agent_evidence_kinds": sorted(
            {item["kind"] for item in agent_evidence if item.get("valid_json") and isinstance(item.get("kind"), str)}
        ),
        "current_passed_evidence_kinds": current_passed_evidence_kinds,
        "grade": grade,
    }
    result["task_success"] = not timed_out and return_code == 0 and bool(grade.get("correct"))
    (run_root / "result.sanitized.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return result


def _paired_summary(results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    items = list(results)

    def task_success(item: dict[str, Any]) -> bool:
        return not item["timed_out"] and item["codex_return_code"] == 0 and bool(item["grade"].get("correct"))

    conditions: dict[str, dict[str, Any]] = {}
    for condition in ("off", "on"):
        selected = [item for item in items if item["condition"] == condition]
        valid_items = [item for item in selected if not item["infrastructure_failure"]]
        successes = sum(task_success(item) for item in valid_items)
        candidate_correct = sum(bool(item["grade"].get("correct")) for item in valid_items)
        valid = len(valid_items)
        observed_skill = sum(bool(item["trace"]["skill_signals"]) for item in selected)
        complete_commands = sum(
            REQUIRED_EVIDENCE.issubset(item["trace"]["executed_evidence_kinds"]) for item in selected
        )
        structured_evidence = sum(
            REQUIRED_EVIDENCE.issubset(item["current_passed_evidence_kinds"]) for item in selected
        )
        conditions[condition] = {
            "runs": len(selected),
            "valid_runs": valid,
            "task_successes": successes,
            "task_success_rate": successes / valid if valid else None,
            "candidate_correct": candidate_correct,
            "candidate_correct_rate": candidate_correct / valid if valid else None,
            "timeouts": sum(bool(item["timed_out"]) for item in valid_items),
            "observed_skill_use": observed_skill,
            "complete_evidence_commands": complete_commands,
            "complete_structured_evidence": structured_evidence,
            "input_tokens": sum(int(item["trace"]["usage"].get("input_tokens", 0)) for item in selected),
            "output_tokens": sum(int(item["trace"]["usage"].get("output_tokens", 0)) for item in selected),
            "duration_seconds": round(sum(float(item["duration_seconds"]) for item in selected), 3),
        }
    paired = []
    for replicate in sorted({int(item["replicate"]) for item in items}):
        pair = {item["condition"]: item for item in items if item["replicate"] == replicate}
        valid_pair = all(not pair[condition]["infrastructure_failure"] for condition in ("off", "on"))
        paired.append(
            {
                "replicate": replicate,
                "valid": valid_pair,
                "off_success": task_success(pair["off"]),
                "on_success": task_success(pair["on"]),
                "off_candidate_correct": bool(pair["off"]["grade"].get("correct")),
                "on_candidate_correct": bool(pair["on"]["grade"].get("correct")),
            }
        )
    valid_pairs = [item for item in paired if item["valid"]]
    comparisons = {
        "on_only_success": sum(item["on_success"] and not item["off_success"] for item in valid_pairs),
        "off_only_success": sum(item["off_success"] and not item["on_success"] for item in valid_pairs),
        "both_succeeded": sum(item["on_success"] and item["off_success"] for item in valid_pairs),
        "neither_succeeded": sum(not item["on_success"] and not item["off_success"] for item in valid_pairs),
    }
    return {"conditions": conditions, "paired_outcomes": paired, "paired_comparisons": comparisons}


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replicates", type=int, default=5)
    parser.add_argument("--parallel", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--effort", choices=("low", "medium", "high", "xhigh"), default="high")
    parser.add_argument(
        "--sandbox",
        choices=("workspace-write", "danger-full-access"),
        default="workspace-write",
        help="use danger-full-access only inside an externally isolated evaluation environment",
    )
    args = parser.parse_args(arguments)
    if not 1 <= args.replicates <= 20 or not 1 <= args.parallel <= 4 or not 60 <= args.timeout <= 3600:
        raise SystemExit("replicates, parallelism, or timeout is outside the audited range")
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing to reuse output directory: {output}")
    output.mkdir(parents=True)
    codex_version = _codex_version(args.codex)
    jobs: list[tuple[int, str]] = [
        (replicate, condition)
        for replicate in range(1, args.replicates + 1)
        for condition in (("off", "on") if replicate % 2 else ("on", "off"))
    ]
    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as executor:
        futures = [
            executor.submit(
                _run_one,
                executable=args.codex,
                model=args.model,
                effort=args.effort,
                sandbox=args.sandbox,
                timeout=args.timeout,
                output=output,
                replicate=replicate,
                condition=condition,
            )
            for replicate, condition in jobs
        ]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            print(
                json.dumps(
                    {
                        "run_id": result["run_id"],
                        "return_code": result["codex_return_code"],
                        "task_success": result["task_success"],
                        "candidate_correct": result["grade"].get("correct", False),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
    results.sort(key=lambda item: (item["replicate"], item["condition"]))
    report = {
        "schema_version": "1.0",
        "kind": "codex-skill-workflow-audit",
        "generated_at": datetime.now(UTC).isoformat(),
        "case": "repair-non-power-of-two-fifo",
        "prompt_hash": hashlib.sha256(PROMPT.encode()).hexdigest(),
        "fixture_hash": _hash_tree(PUBLIC_FIXTURE),
        "hidden_grader_hash": hash_file(HIDDEN_TESTBENCH),
        "skill_hash": _hash_tree(SKILL_ROOT),
        "codex_version": codex_version,
        "model": args.model,
        "reasoning_effort": args.effort,
        "sandbox": args.sandbox,
        "replicates": args.replicates,
        "tool_discovery": discover_tools(),
        "trace_policy": {
            "raw_jsonl_local_only": True,
            "reasoning_content_retained_in_sanitized_results": False,
            "observable_items": ["agent_message", "command_execution", "file_change", "usage"],
        },
        "summary": _paired_summary(results),
        "runs": results,
    }
    report["report_hash"] = hashlib.sha256(canonical_json(report).encode()).hexdigest()
    (output / "report.sanitized.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps({"output": str(output), "report_hash": report["report_hash"], **report["summary"]}, sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
