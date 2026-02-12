#!/usr/bin/env python3
"""Run isolated, paired Codex workflow audits with and without RTL-ASS."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import shutil
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from rtl_ass.integrity import canonical_json, hash_file
from rtl_ass.tools import discover_tools

if __package__:
    from .workflow_cases import CASES, WorkflowCase, get_case
else:
    # Direct-file execution places evals/ rather than the repository root on
    # sys.path. Keep that supported because the documented audit command uses
    # this file directly; module execution continues to use the package import.
    from workflow_cases import CASES, WorkflowCase, get_case  # type: ignore[import-not-found,no-redef]

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / ".agents" / "skills" / "rtl-ass"
DEFAULT_CASE_ID = "repair-non-power-of-two-fifo"
SOURCE_TREE_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
AGENT_RULES = """# Evaluation workspace

Repair only the supplied RTL task. Do not access files outside this repository.
Preserve the interface and latency contract, do not weaken tests, and use only open-source tools.
Generated evidence may be written under artifacts/. Do not commit changes.
"""


def _hash_tree(root: Path) -> str:
    digest = hashlib.sha256()
    paths = (
        item
        for item in root.rglob("*")
        if item.is_file()
        and not item.is_symlink()
        and "__pycache__" not in item.parts
        and item.suffix not in {".pyc", ".pyo"}
    )
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _hash_files(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        content = path.read_bytes()
        name = path.relative_to(ROOT).as_posix().encode("utf-8")
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
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


def _prepare_workspace(workspace: Path, condition: str, case: WorkflowCase | None = None) -> dict[str, str]:
    selected_case = case or get_case(DEFAULT_CASE_ID)
    if condition not in {"off", "on"}:
        raise ValueError(f"unknown evaluation condition: {condition}")
    if workspace.exists():
        raise RuntimeError(f"refusing to reuse evaluation workspace: {workspace}")
    shutil.copytree(selected_case.public_fixture, workspace)
    initial = {
        path.relative_to(workspace).as_posix(): hash_file(path)
        for path in sorted(item for item in workspace.rglob("*") if item.is_file() and not item.is_symlink())
    }
    (workspace / "AGENTS.md").write_text(AGENT_RULES, encoding="utf-8")
    if condition == "on":
        destination = workspace / ".agents" / "skills" / "rtl-ass"
        destination.parent.mkdir(parents=True)
        shutil.copytree(SKILL_ROOT, destination, ignore=SOURCE_TREE_IGNORE)
        shutil.copytree(
            ROOT / "src" / "rtl_ass",
            workspace / "src" / "rtl_ass",
            ignore=SOURCE_TREE_IGNORE,
        )
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
    initial["repository_head"] = _run(["git", "rev-parse", "HEAD"], cwd=workspace).stdout.strip()
    return initial


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
    if "--help" in lowered:
        return kinds
    if "verilator" in lowered or "verify lint" in lowered:
        kinds.add("lint")
    if "iverilog" in lowered or " vvp" in lowered or "verify simulate" in lowered:
        kinds.add("simulation")
    if "verify formal" in lowered or ("yosys" in lowered and "sat" in lowered):
        kinds.add("formal")
    if "verify synth" in lowered or ("yosys" in lowered and "synth" in lowered):
        kinds.add("synthesis")
    if "verify equiv" in lowered or ("yosys" in lowered and "equiv_" in lowered):
        kinds.add("equivalence")
    if " wave query" in lowered or " wave diff" in lowered:
        kinds.add("waveform")
    if "verify sta" in lowered or "opensta" in lowered or " sta " in lowered:
        kinds.add("sta")
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
    workspace_skill = workspace / ".agents" / "skills" / "rtl-ass"
    matching_skill = all(
        candidate.is_file() and not candidate.is_symlink() and hash_file(candidate) == hash_file(SKILL_ROOT / relative)
        for relative in ("SKILL.md", "scripts/rtl_ass.py")
        for candidate in (workspace_skill / relative,)
    )
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
            if matching_skill and ".agents/skills/rtl-ass/scripts/rtl_ass.py" in command:
                skill_signals.add("helper-command")
            if matching_skill and (
                ".agents/skills/rtl-ass/SKILL.md" in command or ".agents/skills/rtl-ass/references" in command
            ):
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
    for path in sorted(workspace.rglob("*.json")):
        if path.name == "run-evidence.json" or path.is_symlink():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(value, dict) or value.get("kind") not in {
            "vcd-query",
            "fst-query",
            "vcd-first-divergence",
            "fst-first-divergence",
            "wave-divergence",
        }:
            continue
        waveform_hash = value.get("waveform_hash")
        records.append(
            {
                "path": path.relative_to(workspace).as_posix(),
                "valid_json": True,
                "kind": "waveform",
                "status": "pass" if value.get("status") in {"complete", "found"} else value.get("status"),
                "input_hash": waveform_hash,
                "top": None,
                "subject_hashes": (
                    [{"index": 0, "path": value.get("waveform"), "content_hash": waveform_hash}]
                    if isinstance(waveform_hash, str)
                    else []
                ),
                "file_hash": hash_file(path),
            }
        )
    return records


def _current_passed_evidence_kinds(
    records: Iterable[dict[str, Any]], *, expected_subjects: Mapping[str, Iterable[str | None]]
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
        if kind not in expected_subjects:
            continue
        required_hashes = {value for value in expected_subjects[kind] if isinstance(value, str)}
        if required_hashes and not required_hashes.issubset(subject_hashes):
            continue
        kinds.add(kind)
    return sorted(kinds)


def _grade(
    workspace: Path,
    run_root: Path,
    initial: dict[str, str],
    case: WorkflowCase | None = None,
) -> dict[str, Any]:
    selected_case = case or get_case(DEFAULT_CASE_ID)
    return selected_case.grade(workspace, run_root, initial)


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
    case: WorkflowCase,
) -> dict[str, Any]:
    run_id = f"pair-{replicate:02d}-{condition}"
    run_root = output / "runs" / run_id
    workspace = run_root / "workspace"
    run_root.mkdir(parents=True)
    initial = _prepare_workspace(workspace, condition, case)
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
        case.prompt,
    ]
    environment = os.environ.copy()
    original_codex_home = Path(environment.get("CODEX_HOME", Path.home() / ".codex"))
    isolated_codex_home = run_root / "codex-home"
    isolated_codex_home.mkdir()
    auth_source = original_codex_home / "auth.json"
    if auth_source.is_file():
        shutil.copy2(auth_source, isolated_codex_home / "auth.json")
    elif "CODEX_API_KEY" not in environment:
        isolated_codex_home.rmdir()
        raise RuntimeError("Codex authentication is unavailable for the isolated evaluation home")
    environment["CODEX_HOME"] = str(isolated_codex_home)
    environment.pop("PYTHONPATH", None)
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
    grade = _grade(workspace, run_root, initial, case)
    expected_subjects = grade.get("expected_agent_evidence_subjects")
    current_passed_evidence_kinds = (
        _current_passed_evidence_kinds(agent_evidence, expected_subjects=expected_subjects)
        if isinstance(expected_subjects, dict)
        else []
    )
    result = {
        "schema_version": "1.0",
        "run_id": run_id,
        "case": case.identifier,
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
    result["deliverable_complete"] = bool(grade.get("complete", grade.get("correct")))
    result["task_success"] = not timed_out and return_code == 0 and result["deliverable_complete"]
    (run_root / "result.sanitized.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return result


def _paired_summary(
    results: Iterable[dict[str, Any]], required_evidence: frozenset[str] | None = None
) -> dict[str, Any]:
    items = list(results)
    required = required_evidence or get_case(DEFAULT_CASE_ID).required_evidence

    def task_success(item: dict[str, Any]) -> bool:
        complete = bool(item.get("deliverable_complete", item["grade"].get("complete", item["grade"].get("correct"))))
        return not item["timed_out"] and item["codex_return_code"] == 0 and complete

    conditions: dict[str, dict[str, Any]] = {}
    for condition in ("off", "on"):
        selected = [item for item in items if item["condition"] == condition]
        valid_items = [item for item in selected if not item["infrastructure_failure"]]
        successes = sum(task_success(item) for item in valid_items)
        candidate_correct = sum(bool(item["grade"].get("correct")) for item in valid_items)
        deliverable_complete = sum(
            bool(item.get("deliverable_complete", item["grade"].get("complete", item["grade"].get("correct"))))
            for item in valid_items
        )
        valid = len(valid_items)
        observed_skill = sum(bool(item["trace"]["skill_signals"]) for item in valid_items)
        complete_commands = sum(required.issubset(item["trace"]["executed_evidence_kinds"]) for item in valid_items)
        structured_evidence = sum(required.issubset(item["current_passed_evidence_kinds"]) for item in valid_items)
        conditions[condition] = {
            "runs": len(selected),
            "valid_runs": valid,
            "task_successes": successes,
            "task_success_rate": successes / valid if valid else None,
            "task_success_wilson_95": _wilson_interval(successes, valid),
            "candidate_correct": candidate_correct,
            "candidate_correct_rate": candidate_correct / valid if valid else None,
            "candidate_correct_wilson_95": _wilson_interval(candidate_correct, valid),
            "deliverable_complete": deliverable_complete,
            "deliverable_complete_rate": deliverable_complete / valid if valid else None,
            "deliverable_complete_wilson_95": _wilson_interval(deliverable_complete, valid),
            "timeouts": sum(bool(item["timed_out"]) for item in valid_items),
            "observed_skill_use": observed_skill,
            "complete_evidence_commands": complete_commands,
            "complete_structured_evidence": structured_evidence,
            "structured_evidence_wilson_95": _wilson_interval(structured_evidence, valid),
            "input_tokens": sum(int(item["trace"]["usage"].get("input_tokens", 0)) for item in valid_items),
            "output_tokens": sum(int(item["trace"]["usage"].get("output_tokens", 0)) for item in valid_items),
            "duration_seconds": round(sum(float(item["duration_seconds"]) for item in valid_items), 3),
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
                "off_deliverable_complete": bool(
                    pair["off"].get(
                        "deliverable_complete",
                        pair["off"]["grade"].get("complete", pair["off"]["grade"].get("correct")),
                    )
                ),
                "on_deliverable_complete": bool(
                    pair["on"].get(
                        "deliverable_complete",
                        pair["on"]["grade"].get("complete", pair["on"]["grade"].get("correct")),
                    )
                ),
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


def _wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> list[float] | None:
    if total == 0:
        return None
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    margin = z * math.sqrt(proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total)) / denominator
    return [round(max(0.0, center - margin), 6), round(min(1.0, center + margin), 6)]


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replicates", type=int, default=5)
    parser.add_argument("--parallel", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--effort", choices=("low", "medium", "high", "xhigh"), default="high")
    parser.add_argument("--case", choices=sorted(CASES), default=DEFAULT_CASE_ID)
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
    case = get_case(args.case)
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
                case=case,
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
                        "deliverable_complete": result["deliverable_complete"],
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
        "case": case.identifier,
        "prompt_hash": hashlib.sha256(case.prompt.encode()).hexdigest(),
        "fixture_hash": _hash_tree(case.public_fixture),
        "hidden_grader_hash": _hash_tree(case.public_fixture.parent / "private"),
        "harness_hash": _hash_files((Path(__file__).resolve(), ROOT / "evals" / "workflow_cases.py")),
        "skill_hash": _hash_tree(SKILL_ROOT),
        "runtime_hash": _hash_tree(ROOT / "src" / "rtl_ass"),
        "codex_version": codex_version,
        "model": args.model,
        "reasoning_effort": args.effort,
        "sandbox": args.sandbox,
        "replicates": args.replicates,
        "required_evidence": sorted(case.required_evidence),
        "tool_discovery": discover_tools(),
        "trace_policy": {
            "raw_jsonl_local_only": True,
            "reasoning_content_retained_in_sanitized_results": False,
            "observable_items": ["agent_message", "command_execution", "file_change", "usage"],
        },
        "summary": _paired_summary(results, case.required_evidence),
        "runs": results,
    }
    report["on_payload_hash"] = hashlib.sha256(f"{report['skill_hash']}:{report['runtime_hash']}".encode()).hexdigest()
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
