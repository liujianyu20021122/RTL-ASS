#!/usr/bin/env python3
"""Run isolated, paired Codex workflow audits with and without RTL-ASS."""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import fcntl
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import signal
import sqlite3
import subprocess
import threading
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from rtl_ass.errors import RtlAssError
from rtl_ass.integrity import canonical_json, hash_file
from rtl_ass.kb.database import KnowledgeDatabase
from rtl_ass.kb.gates import validate_run_evidence
from rtl_ass.kb.models import RecordRole, RecordStatus
from rtl_ass.kb.packs import load_knowledge_pack
from rtl_ass.kb.retrieval import build_retrieval_receipt, validate_retrieval_receipt
from rtl_ass.tools import discover_tools
from rtl_ass.waveform import validate_waveform_evidence

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
REASONING_EFFORTS = ("none", "low", "medium", "high", "xhigh", "max")
SOURCE_TREE_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
OPEN_TOOL_COMMANDS = {
    "gtkwave": ("gtkwave", "fst2vcd"),
    "iverilog": ("iverilog", "vvp"),
    "opensta": ("sta", "opensta"),
    "verilator": ("verilator",),
    "yosys": ("yosys",),
}
SANDBOX_HOME = Path("/opt/rtl-ass-home")
SANDBOX_CODEX_HOME = SANDBOX_HOME / ".codex"
NETWORK_EXECUTABLES = frozenset({"curl", "ftp", "nc", "ncat", "scp", "sftp", "ssh", "wget"})
PROPRIETARY_EXECUTABLES = frozenset(
    {"dc_shell", "genus", "innovus", "questa", "quartus", "quartus_sh", "vcs", "verdi", "vivado", "vsim", "xrun"}
)
NESTED_AGENT_EXECUTABLES = frozenset({"claude", "codex", "gemini", "openai"})
PACKAGE_EXECUTABLES = frozenset({"apt", "apt-get", "cargo", "npm", "pip", "pip3", "pnpm", "yarn"})
NETWORK_ERROR_MARKERS = (
    "connection failed",
    "error sending request",
    "failed to lookup address information",
    "request timed out",
    "stream disconnected before completion",
)
RESOURCE_LOCK = Path(f"/run/user/{os.getuid()}/rtl-ass-codex-ab.lock")


@dataclass(frozen=True)
class ResourcePolicy:
    memory_high_bytes: int = 2 * 1024**3
    memory_kill_bytes: int = 3 * 1024**3
    memory_max_bytes: int = 4 * 1024**3
    memory_swap_max_bytes: int = 512 * 1024**2
    host_available_kill_bytes: int = 8 * 1024**3
    cpu_quota_percent: int = 300
    tasks_max: int = 384
    sample_interval_seconds: float = 0.5
    runtime_grace_seconds: int = 60

    def __post_init__(self) -> None:
        if not 0 < self.memory_high_bytes < self.memory_kill_bytes < self.memory_max_bytes:
            raise ValueError("resource memory thresholds must be strictly increasing")
        if (
            min(
                self.memory_swap_max_bytes,
                self.host_available_kill_bytes,
                self.cpu_quota_percent,
                self.tasks_max,
                self.runtime_grace_seconds,
            )
            <= 0
        ):
            raise ValueError("resource policy values must be positive")


DEFAULT_RESOURCE_POLICY = ResourcePolicy()


@dataclass(frozen=True)
class TransportPolicy:
    network_stall_seconds: int = 120
    sample_interval_seconds: float = 1.0

    def __post_init__(self) -> None:
        if self.network_stall_seconds <= 0 or self.sample_interval_seconds <= 0:
            raise ValueError("transport policy values must be positive")


DEFAULT_TRANSPORT_POLICY = TransportPolicy()
AGENT_RULES = """# Evaluation workspace

Repair only the supplied RTL task. Do not access files outside this repository.
Preserve the interface and latency contract, do not weaken tests, and use only open-source tools.
Generated evidence may be written under artifacts/. Do not commit changes.
"""
RETRIEVAL_AGENT_RULES = """
An approved evaluation index is available at `.rtl-ass/eval.db` in namespace `eval:retrieval`.
When relevant, use a bounded search with explicit `--match any --actor codex --output artifacts/rtl-ass/retrieval.json`, then inspect
only selected returned records with `kb show <id> --include-content`. The index is advisory and may be empty.
"""
RETRIEVAL_ABLATION_ROLES = frozenset({"design-pattern", "verification-pattern"})


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


def _validate_retrieval_ablation_pack(path: Path, case: WorkflowCase) -> dict[str, Any]:
    """Reject direct task artifacts and require an explicit semantic contamination review."""
    pack = load_knowledge_pack(path)
    case_hashes = {
        hash_file(candidate)
        for root in (case.public_fixture, case.public_fixture.parent / "private")
        for candidate in root.rglob("*")
        if candidate.is_file() and not candidate.is_symlink()
    }
    if not 1 <= len(pack["records"]) <= 3:
        raise RtlAssError("unsafe_retrieval_ablation", "retrieval ablation packs require 1-3 bounded records")
    reviewed_hashes: list[str] = []
    for record in pack["records"]:
        if (
            record["role"] not in RETRIEVAL_ABLATION_ROLES
            or record["content_hash"] in case_hashes
            or record["source_path"].startswith("evals/workflow_cases/")
            or record["metadata"].get("contamination_review")
            != "no-task-source-no-test-no-reference-no-patch-no-grader-output"
        ):
            raise RtlAssError(
                "unsafe_retrieval_ablation",
                "retrieval pack contains an unreviewed or task-identical record",
                {"record": record["key"]},
            )
        reviewed_hashes.append(record["content_hash"])
    return {
        "status": "pass",
        "policy_version": "1.0",
        "pack_hash": pack["pack_hash"],
        "record_count": len(pack["records"]),
        "record_content_hashes": reviewed_hashes,
        "case_artifact_hash_count": len(case_hashes),
        "direct_hash_overlap": False,
        "allowed_roles": sorted(RETRIEVAL_ABLATION_ROLES),
        "semantic_review_marker_required": True,
        "boundary": "hash separation is automatic; semantic absence of answer content is an explicit human review assertion",
    }


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


def _prepare_workspace(
    workspace: Path,
    condition: str,
    case: WorkflowCase | None = None,
    *,
    skill_root: Path = SKILL_ROOT,
    ablation: str = "skill",
    retrieval_pack: Path | None = None,
) -> dict[str, str]:
    selected_case = case or get_case(DEFAULT_CASE_ID)
    if condition not in {"off", "on"}:
        raise ValueError(f"unknown evaluation condition: {condition}")
    if workspace.exists():
        raise RuntimeError(f"refusing to reuse evaluation workspace: {workspace}")
    if ablation not in {"skill", "retrieval"}:
        raise ValueError(f"unknown ablation: {ablation}")
    if (ablation == "retrieval") != (retrieval_pack is not None):
        raise ValueError("retrieval ablation requires exactly one explicit knowledge pack")
    shutil.copytree(selected_case.public_fixture, workspace)
    initial = {
        path.relative_to(workspace).as_posix(): hash_file(path)
        for path in sorted(item for item in workspace.rglob("*") if item.is_file() and not item.is_symlink())
    }
    agent_rules = AGENT_RULES + (RETRIEVAL_AGENT_RULES if ablation == "retrieval" else "")
    (workspace / "AGENTS.md").write_text(agent_rules, encoding="utf-8")
    if condition == "on" or ablation == "retrieval":
        destination = workspace / ".agents" / "skills" / "rtl-ass"
        destination.parent.mkdir(parents=True)
        shutil.copytree(skill_root, destination, ignore=SOURCE_TREE_IGNORE)
        if not (skill_root / "runtime").is_dir():
            if (workspace / "pyproject.toml").exists():
                raise RuntimeError("source-tree Skill evaluation would overwrite the fixture pyproject.toml")
            shutil.copy2(ROOT / "pyproject.toml", workspace / "pyproject.toml")
            shutil.copytree(
                ROOT / "src" / "rtl_ass",
                workspace / "src" / "rtl_ass",
                ignore=SOURCE_TREE_IGNORE,
            )
    if ablation == "retrieval":
        database = KnowledgeDatabase(workspace / ".rtl-ass" / "eval.db")
        database.initialize(actor="evaluation-harness")
        if condition == "on" and retrieval_pack is not None:
            database.import_pack(
                retrieval_pack,
                namespace="eval:retrieval",
                actor="evaluation-harness",
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


def _redact_value(value: Any, workspace: Path) -> Any:
    if isinstance(value, str):
        return _redact(value, workspace)
    if isinstance(value, list):
        return [_redact_value(item, workspace) for item in value]
    if isinstance(value, dict):
        return {key: _redact_value(item, workspace) for key, item in value.items()}
    return value


def _redact_host_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace(ROOT.as_posix(), "$RTL_ASS_ROOT").replace(Path.home().as_posix(), "$HOME")
    if isinstance(value, list):
        return [_redact_host_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_host_value(item) for key, item in value.items()}
    return value


def _command_kinds(command: str) -> set[str]:
    kinds: set[str] = set()
    helper_kinds = {
        "lint": "lint",
        "simulate": "simulation",
        "formal": "formal",
        "synth": "synthesis",
        "equiv": "equivalence",
        "sta": "sta",
    }
    for segment in _expanded_command_segments(command):
        if not segment or any(argument in {"--help", "-h"} for argument in segment[1:]):
            continue
        helper_arguments = _rtl_ass_arguments(segment)
        if helper_arguments is not None:
            if len(helper_arguments) >= 2 and helper_arguments[0] == "verify":
                kind = helper_kinds.get(helper_arguments[1])
                if kind is not None:
                    kinds.add(kind)
            elif (
                len(helper_arguments) >= 2
                and helper_arguments[0] == "wave"
                and helper_arguments[1]
                in {
                    "query",
                    "diff",
                }
            ):
                kinds.add("waveform")
            continue
        executable = Path(segment[0]).name.lower()
        arguments = [argument.lower() for argument in segment[1:]]
        if executable == "verilator":
            kinds.add("simulation" if "--binary" in arguments else "lint")
        elif executable in {"iverilog", "vvp"}:
            kinds.add("simulation")
        elif executable == "sby":
            kinds.add("formal")
        elif executable == "eqy":
            kinds.add("equivalence")
        elif executable == "yosys":
            script = " ".join(arguments[index + 1] for index, argument in enumerate(arguments[:-1]) if argument == "-p")
            if re.search(r"\bsynth(?:_[a-z0-9]+)?\b", script):
                kinds.add("synthesis")
            if re.search(r"\bsat\b", script):
                kinds.add("formal")
            if re.search(r"\bequiv_[a-z0-9_]+\b", script):
                kinds.add("equivalence")
        elif executable in {"fst2vcd", "gtkwave"}:
            kinds.add("waveform")
        elif executable in {"opensta", "sta"}:
            kinds.add("sta")
    return kinds


def _command_segments(command: str) -> list[list[str]]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        return []
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token and set(token).issubset({";", "&", "|"}):
            if current:
                segments.append(current)
                current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments


def _expanded_command_segments(command: str) -> list[list[str]]:
    segments = _command_segments(command)
    for segment in tuple(segments):
        if not segment or Path(segment[0]).name not in {"bash", "dash", "sh", "zsh"}:
            continue
        for index, argument in enumerate(segment[1:-1], start=1):
            if argument.startswith("-") and "c" in argument[1:]:
                segments.extend(_command_segments(segment[index + 1]))
                break
    return segments


def _skill_command_signals(command: str, *, matching_skill: bool) -> set[str]:
    if not matching_skill:
        return set()
    signals: set[str] = set()
    readers = {"awk", "bat", "cat", "grep", "head", "less", "more", "nl", "rg", "sed", "tail"}
    segments = _expanded_command_segments(command)
    for segment in segments:
        if not segment:
            continue
        executable = Path(segment[0]).name
        arguments = segment[1:]
        direct_helper = segment[0].endswith("/.agents/skills/rtl-ass/scripts/rtl_ass.py") or segment[0] == (
            ".agents/skills/rtl-ass/scripts/rtl_ass.py"
        )
        python_helper = executable in {"python", "python3"} and any(
            argument.endswith("/.agents/skills/rtl-ass/scripts/rtl_ass.py")
            or argument == ".agents/skills/rtl-ass/scripts/rtl_ass.py"
            for argument in arguments
        )
        if direct_helper or python_helper:
            signals.add("helper-command")
        if executable in readers and any(
            argument.endswith("/.agents/skills/rtl-ass/SKILL.md")
            or argument == ".agents/skills/rtl-ass/SKILL.md"
            or "/.agents/skills/rtl-ass/references/" in argument
            or argument.startswith(".agents/skills/rtl-ass/references/")
            for argument in arguments
        ):
            signals.add("skill-file-read")
    return signals


def _command_policy_findings(command: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for segment in _expanded_command_segments(command):
        if not segment:
            continue
        executable = Path(segment[0]).name.lower()
        arguments = [argument.lower() for argument in segment[1:]]
        reason: str | None = None
        if executable in NETWORK_EXECUTABLES or (
            executable == "git"
            and (
                any(argument in {"clone", "fetch", "pull", "ls-remote"} for argument in arguments[:2])
                or arguments[:2] == ["submodule", "update"]
            )
        ):
            reason = "network-command"
        elif executable in PACKAGE_EXECUTABLES and any(
            argument in {"add", "i", "install", "update", "upgrade"} for argument in arguments[:3]
        ):
            reason = "package-network-command"
        elif executable in PROPRIETARY_EXECUTABLES:
            reason = "proprietary-tool-command"
        elif (executable in NESTED_AGENT_EXECUTABLES and not _is_nonexecuting_cli_probe(arguments)) or (
            executable in {"python", "python3"}
            and arguments[:2] in (["-m", "openai"], ["-m", "codex"])
            and not _is_nonexecuting_cli_probe(arguments[2:])
        ):
            reason = "nested-agent-command"
        elif (
            executable in {"python", "python3"}
            and arguments[:2] in (["-m", "pip"], ["-m", "ensurepip"])
            and any(argument in {"install", "uninstall", "update", "upgrade"} for argument in arguments[2:5])
        ):
            reason = "package-network-command"
        if reason is not None:
            findings.append({"reason": reason, "executable": executable})
    return findings


def _is_nonexecuting_cli_probe(arguments: list[str]) -> bool:
    return any(argument in {"--help", "-h"} for argument in arguments) or arguments in (["--version"], ["version"])


def _workflow_audit(
    trace: Mapping[str, Any],
    case: WorkflowCase,
    condition: str,
    grade: Mapping[str, Any],
    *,
    ablation: str = "skill",
) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    commands = trace.get("commands", [])
    if isinstance(commands, list):
        for index, item in enumerate(commands):
            if not isinstance(item, dict) or not isinstance(item.get("command"), str):
                continue
            for finding in _command_policy_findings(item["command"]):
                violations.append({"command_index": index, **finding})
    skill_signals = trace.get("skill_signals", [])
    if ablation == "skill" and condition == "off" and skill_signals:
        violations.append({"reason": "skill-visible-in-off-condition"})
    protected = grade.get("protected_files_unchanged")
    if protected is False:
        violations.append({"reason": "protected-fixture-changed"})
    if trace.get("invalid_jsonl_lines"):
        violations.append({"reason": "invalid-trace-jsonl"})
    executed = {value for value in trace.get("executed_evidence_kinds", []) if isinstance(value, str)}
    extra_evidence = sorted(executed - case.allowed_evidence)
    return {
        "policy_version": "1.0",
        "condition": condition,
        "ablation": ablation,
        "skill_activated": bool(skill_signals),
        "allowed_evidence": sorted(case.allowed_evidence),
        "required_evidence": sorted(case.required_evidence),
        "executed_evidence_outside_case_policy": extra_evidence,
        "violations": violations,
        "compliant": not violations and not extra_evidence,
        "monitoring_boundary": (
            "observable Codex command/file-change events plus independent workspace grading; "
            "opaque behavior inside generated programs is not inferred"
        ),
    }


def _workflow_efficiency(trace: Mapping[str, Any], evidence: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    identities: dict[tuple[str, str], set[str]] = {}
    for item in evidence:
        kind = item.get("kind")
        input_hash = item.get("input_hash")
        path = item.get("path")
        if (
            item.get("strictly_valid")
            and kind != "waveform"
            and isinstance(kind, str)
            and isinstance(input_hash, str)
            and isinstance(path, str)
        ):
            identities.setdefault((kind, input_hash), set()).add(path)
    duplicates = [
        {"kind": kind, "input_hash": input_hash, "paths": sorted(paths)}
        for (kind, input_hash), paths in sorted(identities.items())
        if len(paths) > 1
    ]
    commands = trace.get("commands")
    ready_gate_index: int | None = None
    post_ready: list[dict[str, Any]] = []
    if isinstance(commands, list):
        for index, item in enumerate(commands):
            if ready_gate_index is None and _successful_ready_gate(item):
                ready_gate_index = index
                continue
            if ready_gate_index is None or not isinstance(item, dict) or not isinstance(item.get("command"), str):
                continue
            kinds = sorted(_command_kinds(item["command"]))
            if kinds:
                post_ready.append({"command_index": index, "evidence_kinds": kinds})
    return {
        "policy_version": "1.0",
        "duplicate_evidence_identities": duplicates,
        "redundant_evidence_execution_count": sum(len(item["paths"]) - 1 for item in duplicates),
        "successful_ready_gate_command_index": ready_gate_index,
        "post_ready_eda_commands": post_ready,
        "efficient": not duplicates and not post_ready,
        "interpretation": (
            "efficiency diagnostics do not change candidate correctness, evidence validity, workflow compliance, "
            "or infrastructure attribution"
        ),
    }


def _successful_ready_gate(item: object) -> bool:
    if (
        not isinstance(item, dict)
        or item.get("status") != "completed"
        or item.get("exit_code") != 0
        or not isinstance(item.get("command"), str)
    ):
        return False
    for segment in _expanded_command_segments(item["command"]):
        tool_arguments = _rtl_ass_arguments(segment)
        if (
            tool_arguments is not None
            and tool_arguments[:2] == ["verify", "summarize"]
            and "--require-ready" in tool_arguments[2:]
        ):
            return True
    return False


def _rtl_ass_arguments(segment: Sequence[str]) -> list[str] | None:
    if not segment:
        return None
    executable = Path(segment[0]).name
    arguments = list(segment[1:])
    if executable == "rtl-ass":
        return arguments
    if executable not in {"python", "python3"}:
        return None
    for index, argument in enumerate(arguments):
        if argument.endswith("/rtl_ass.py") or argument == "rtl_ass.py":
            return arguments[index + 1 :]
    if arguments[:2] == ["-m", "rtl_ass"]:
        return arguments[2:]
    return None


def _workspace_retrieval(
    workspace: Path,
    trace: Mapping[str, Any],
    *,
    expected_database_hash: str | None = None,
) -> dict[str, Any]:
    """Validate retrieval receipts and correlate returned records with observable content reads."""
    database_path = workspace / ".rtl-ass" / "eval.db"
    current_database_hash = (
        hash_file(database_path) if database_path.is_file() and not database_path.is_symlink() else None
    )
    database_integrity = {
        "expected_hash": expected_database_hash,
        "current_hash": current_database_hash,
        "unchanged": expected_database_hash is None or current_database_hash == expected_database_hash,
    }
    inspected: set[str] = set()
    commands = trace.get("commands")
    if isinstance(commands, list):
        for item in commands:
            if (
                not isinstance(item, dict)
                or item.get("status") != "completed"
                or item.get("exit_code") != 0
                or not isinstance(item.get("command"), str)
            ):
                continue
            for segment in _expanded_command_segments(item["command"]):
                arguments = _rtl_ass_arguments(segment)
                if (
                    arguments is not None
                    and len(arguments) >= 3
                    and arguments[:2] == ["kb", "show"]
                    and "--include-content" in arguments[3:]
                ):
                    inspected.add(arguments[2])

    receipts: list[dict[str, Any]] = []
    returned: set[str] = set()
    for path in sorted(workspace.rglob("*.json")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            continue
        if not isinstance(value, dict) or value.get("kind") != "knowledge-retrieval":
            continue
        reason: str | None = None
        try:
            receipt = _validate_workspace_retrieval_receipt(
                value,
                workspace,
                expected_database_hash=expected_database_hash,
            )
        except RtlAssError as exc:
            reason = exc.code
            receipt = value
        raw_results = receipt.get("results")
        results = raw_results if isinstance(raw_results, list) else []
        result_ids: list[str] = []
        for item in results:
            record_id = item.get("id") if isinstance(item, dict) else None
            if isinstance(record_id, str):
                result_ids.append(record_id)
        if reason is None:
            returned.update(result_ids)
        content_hashes = [
            item.get("content_hash")
            for item in results
            if isinstance(item, dict) and isinstance(item.get("content_hash"), str)
        ]
        receipts.append(
            {
                "path": path.relative_to(workspace).as_posix(),
                "strictly_valid": reason is None,
                "reason": reason,
                "file_hash": hash_file(path),
                "retrieval_hash": receipt.get("retrieval_hash"),
                "namespaces": receipt.get("namespaces"),
                "limit": receipt.get("limit"),
                "result_count": receipt.get("result_count"),
                "result_ids": result_ids,
                "result_content_hashes": content_hashes,
            }
        )
    inspected_returned = returned & inspected
    return {
        "policy_version": "1.0",
        "database_integrity": database_integrity,
        "receipts": receipts,
        "valid_receipt_count": sum(bool(item["strictly_valid"]) for item in receipts),
        "returned_result_ids": sorted(returned),
        "inspected_result_ids": sorted(inspected_returned),
        "uninspected_result_ids": sorted(returned - inspected),
        "inspected_outside_valid_receipts": sorted(inspected - returned),
        "interpretation": (
            "a valid receipt proves bounded retrieval inputs and outputs; a successful kb show --include-content "
            "command is separately required to count a returned record as inspected"
        ),
    }


def _validate_workspace_retrieval_receipt(
    value: object,
    workspace: Path,
    *,
    expected_database_hash: str | None = None,
) -> dict[str, Any]:
    receipt = validate_retrieval_receipt(value)
    database_path = workspace / ".rtl-ass" / "eval.db"
    if not database_path.exists():
        if expected_database_hash is not None:
            raise RtlAssError("retrieval_database_changed", "evaluation retrieval database is missing")
        return receipt
    if database_path.is_symlink() or not database_path.is_file():
        raise RtlAssError("retrieval_database_invalid", "evaluation retrieval database must be a regular file")
    if expected_database_hash is not None and hash_file(database_path) != expected_database_hash:
        raise RtlAssError(
            "retrieval_database_changed",
            "evaluation retrieval database changed after the treatment was prepared",
        )
    try:
        database = KnowledgeDatabase(database_path)
        audit = database.verify_audit_chain()
        if not audit["valid"]:
            raise RtlAssError("retrieval_database_invalid", "evaluation retrieval database audit chain is invalid")
        filters = receipt["filters"]
        results = database.search(
            receipt["query"],
            namespaces=receipt["namespaces"],
            limit=receipt["limit"],
            role=RecordRole(filters["role"]) if filters["role"] is not None else None,
            status=RecordStatus(filters["status"]) if filters["status"] is not None else None,
            match_mode=filters["match_mode"],
        )
        expected = build_retrieval_receipt(
            results,
            actor=receipt["actor"],
            query=receipt["query"],
            namespaces=receipt["namespaces"],
            limit=receipt["limit"],
            role=filters["role"],
            status=filters["status"],
            match_mode=filters["match_mode"],
        )
    except sqlite3.Error as exc:
        raise RtlAssError("retrieval_database_invalid", "evaluation retrieval database cannot be audited") from exc
    if expected != receipt:
        raise RtlAssError(
            "retrieval_result_mismatch",
            "retrieval receipt does not match a current replay against the evaluation database",
        )
    return receipt


def _network_error_message(event: Mapping[str, Any]) -> str | None:
    message: Any = None
    if event.get("type") == "error":
        message = event.get("message")
    elif event.get("type") == "item.completed":
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "error":
            message = item.get("message")
    if not isinstance(message, str):
        return None
    lowered = message.lower()
    return message if any(marker in lowered for marker in NETWORK_ERROR_MARKERS) else None


def _parse_trace(path: Path, workspace: Path, skill_root: Path = SKILL_ROOT) -> dict[str, Any]:
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
        candidate.is_file() and not candidate.is_symlink() and hash_file(candidate) == hash_file(skill_root / relative)
        for relative in ("SKILL.md", "scripts/rtl_ass.py")
        for candidate in (workspace_skill / relative,)
    )
    invalid_lines = 0
    network_error_count = 0
    terminal_network_error = False
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            invalid_lines += 1
            continue
        event_type = event.get("type")
        if isinstance(event_type, str):
            event_counts[event_type] += 1
        if _network_error_message(event) is not None:
            network_error_count += 1
            terminal_network_error = True
        elif event_type != "error":
            terminal_network_error = False
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
            skill_signals.update(_skill_command_signals(command, matching_skill=matching_skill))
    return {
        "event_counts": dict(sorted(event_counts.items())),
        "item_counts": dict(sorted(item_counts.items())),
        "reasoning_content_retained": False,
        "invalid_jsonl_lines": invalid_lines,
        "network_error_count": network_error_count,
        "terminal_network_error": terminal_network_error,
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
        validation_error: str | None = None
        if isinstance(value, dict):
            try:
                _validate_workspace_run_evidence(value, workspace)
            except RtlAssError as exc:
                validation_error = exc.code
        else:
            validation_error = "invalid_evidence"
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
                "strictly_valid": validation_error is None,
                "reason": validation_error,
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
        waveform_path = value.get("waveform")
        try:
            validate_waveform_evidence(value)
            waveform_contract_valid = True
        except RtlAssError:
            waveform_contract_valid = False
        waveform_valid = bool(
            isinstance(waveform_path, str)
            and isinstance(waveform_hash, str)
            and _workspace_file_matches(workspace, waveform_path, waveform_hash)
            and waveform_contract_valid
        )
        records.append(
            {
                "path": path.relative_to(workspace).as_posix(),
                "valid_json": True,
                "strictly_valid": waveform_valid,
                "reason": None if waveform_valid else "invalid_waveform_evidence",
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


def _validate_workspace_run_evidence(value: Mapping[str, Any], workspace: Path) -> None:
    validate_run_evidence(value)
    _require_workspace_evidence_paths(value, workspace)
    hashed_paths = [
        item
        for field in ("subject_hashes", "artifact_hashes")
        for item in value.get(field, [])
        if isinstance(item, dict)
    ]
    for item in hashed_paths:
        path_value = item.get("path")
        content_hash = item.get("content_hash")
        if (
            not isinstance(path_value, str)
            or not isinstance(content_hash, str)
            or not _workspace_file_matches(workspace, path_value, content_hash)
        ):
            raise RtlAssError("evidence_content_changed", "evaluation evidence content is missing or stale")
    evidence_file = value.get("evidence_file")
    if not isinstance(evidence_file, str):
        raise RtlAssError("invalid_evidence_path", "evidence file path must be a string")
    path = Path(evidence_file)
    if not path.is_absolute():
        path = workspace / path
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RtlAssError("evidence_file_invalid", "run-evidence JSON is unavailable or invalid") from exc
    if stored != value:
        raise RtlAssError("evidence_file_changed", "run-evidence JSON no longer matches its record")


def _workspace_file_matches(workspace: Path, path_value: str, expected_hash: str) -> bool:
    path = Path(path_value)
    if not path.is_absolute():
        path = workspace / path
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(workspace.resolve())
    except (FileNotFoundError, OSError, ValueError):
        return False
    return resolved.is_file() and not path.is_symlink() and hash_file(resolved) == expected_hash


def _require_workspace_evidence_paths(value: Mapping[str, Any], workspace: Path) -> None:
    path_values = [value.get("evidence_file")]
    path_values.extend(value.get("artifacts", []))
    path_values.extend(subject.get("path") for subject in value.get("subject_hashes", []) if isinstance(subject, dict))
    for path_value in path_values:
        if not isinstance(path_value, str):
            raise RtlAssError("invalid_evidence_path", "evidence path must be a string")
        path = Path(path_value)
        if not path.is_absolute():
            path = workspace / path
        try:
            path.resolve(strict=True).relative_to(workspace.resolve())
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise RtlAssError("evidence_path_escape", "evaluation evidence must remain inside the workspace") from exc
        if path.is_symlink():
            raise RtlAssError("evidence_symlink", "evaluation evidence paths cannot be symlinks")


def _current_passed_evidence_kinds(
    records: Iterable[dict[str, Any]], *, expected_subjects: Mapping[str, Iterable[str | None]]
) -> list[str]:
    kinds: set[str] = set()
    for record in records:
        kind = record.get("kind")
        if not record.get("strictly_valid") or record.get("status") != "pass" or not isinstance(kind, str):
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


def _disabled_host_skill_paths(codex_home: Path) -> list[Path]:
    paths = [SKILL_ROOT / "SKILL.md"]
    user_skills = codex_home / "skills"
    if user_skills.is_dir():
        paths.extend(
            path
            for path in user_skills.glob("*/SKILL.md")
            if path.parent.name != ".system" and path.is_file() and not path.is_symlink()
        )
    plugin_cache = codex_home / "plugins" / "cache"
    if plugin_cache.is_dir():
        paths.extend(path for path in plugin_cache.rglob("SKILL.md") if path.is_file() and not path.is_symlink())
    return sorted({path.resolve() for path in paths})


def _skills_config_override(paths: Iterable[Path]) -> str:
    entries = ",".join(f"{{path={json.dumps(path.as_posix())},enabled=false}}" for path in paths)
    return f"skills.config=[{entries}]"


def _codex_package(executable: str) -> tuple[Path, Path]:
    resolved = shutil.which(executable)
    if resolved is None:
        raise RuntimeError(f"cannot locate Codex executable: {executable}")
    launcher = Path(resolved).resolve()
    package = launcher.parent.parent
    package_json = package / "package.json"
    if not package_json.is_file():
        raise RuntimeError("outer bwrap requires the npm-distributed Codex executable")
    candidates = sorted(package.glob("node_modules/@openai/codex-*/vendor/*/bin/codex"))
    native = [path for path in candidates if path.is_file() and os.access(path, os.X_OK)]
    if len(native) != 1:
        raise RuntimeError("outer bwrap could not resolve exactly one native Codex executable")
    return package, native[0].relative_to(package)


def _parent_directory_args(path: Path) -> list[str]:
    result: list[str] = []
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        result.extend(("--dir", current.as_posix()))
    return result


def _open_tool_prefixes() -> dict[str, Path]:
    """Resolve non-system open-tool prefixes from the evaluator's PATH."""
    prefixes: dict[str, Path] = {}
    for name, commands in OPEN_TOOL_COMMANDS.items():
        executable = next((resolved for command in commands if (resolved := shutil.which(command)) is not None), None)
        if executable is None:
            continue
        executable_path = Path(executable).resolve()
        if not executable_path.is_file() or not os.access(executable_path, os.X_OK):
            continue
        prefix = executable_path.parent.parent if executable_path.parent.name == "bin" else executable_path.parent
        if prefix == Path("/usr"):
            # /usr is already mounted read-only in the sandbox and its bin
            # directory is already present in the fixed sandbox PATH.
            continue
        if prefix == Path("/") or not prefix.is_dir():
            raise RuntimeError(f"cannot derive a bounded installation prefix for open tool: {name}")
        prefixes[name] = prefix
    return prefixes


def _outer_bwrap_command(
    *,
    executable: str,
    workspace: Path,
    codex_home: Path,
    temporary_directory: Path,
    model: str,
    effort: str,
    prompt: str,
) -> tuple[list[str], list[dict[str, str]]]:
    if (
        not temporary_directory.is_dir()
        or temporary_directory.is_symlink()
        or temporary_directory.parent.resolve() != workspace.parent.resolve()
    ):
        raise RuntimeError("outer bwrap temporary directory must be a real run-local directory")
    agent_uid = os.getuid()
    agent_gid = os.getgid()
    if agent_uid == 0 or agent_gid == 0:
        raise RuntimeError("outer bwrap must be launched by an unprivileged user before sudo supervision")
    package, native_relative = _codex_package(executable)
    available_tools = _open_tool_prefixes()
    path_entries = [f"/opt/rtl-tools/{name}/bin" for name in sorted(available_tools)]
    command = [
        "bwrap",
        "--die-with-parent",
        "--new-session",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--unshare-cgroup-try",
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind",
        "/bin",
        "/bin",
        "--ro-bind",
        "/lib",
        "/lib",
        "--ro-bind",
        "/lib64",
        "/lib64",
        "--ro-bind",
        "/etc",
        "/etc",
        "--dir",
        "/run",
        "--dir",
        "/run/systemd",
        "--dir",
        "/run/systemd/resolve",
        "--ro-bind",
        "/run/systemd/resolve/stub-resolv.conf",
        "/run/systemd/resolve/stub-resolv.conf",
        "--ro-bind",
        "/sys",
        "/sys",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--dir",
        "/tmp",
        "--bind",
        temporary_directory.as_posix(),
        "/tmp",
        "--dir",
        "/opt",
        "--dir",
        "/opt/codex",
        "--ro-bind",
        package.as_posix(),
        "/opt/codex",
        *_parent_directory_args(workspace.parent),
        "--bind",
        workspace.as_posix(),
        workspace.as_posix(),
        "--dir",
        SANDBOX_CODEX_HOME.as_posix(),
        "--bind",
        codex_home.as_posix(),
        SANDBOX_CODEX_HOME.as_posix(),
        "--dir",
        "/opt/rtl-tools",
    ]
    mounts = [
        {"source": package.as_posix(), "target": "/opt/codex", "mode": "read-only"},
        {
            "source": "/run/systemd/resolve/stub-resolv.conf",
            "target": "/run/systemd/resolve/stub-resolv.conf",
            "mode": "read-only",
        },
        {"source": workspace.as_posix(), "target": workspace.as_posix(), "mode": "read-write"},
        {"source": codex_home.as_posix(), "target": SANDBOX_CODEX_HOME.as_posix(), "mode": "read-write"},
        {"source": temporary_directory.as_posix(), "target": "/tmp", "mode": "read-write"},
    ]
    for name, source in sorted(available_tools.items()):
        target = f"/opt/rtl-tools/{name}"
        command.extend(("--dir", target, "--ro-bind", source.as_posix(), target))
        mounts.append({"source": source.as_posix(), "target": target, "mode": "read-only"})
    command.extend(
        (
            "--setenv",
            "HOME",
            SANDBOX_HOME.as_posix(),
            "--setenv",
            "CODEX_HOME",
            SANDBOX_CODEX_HOME.as_posix(),
            "--setenv",
            "TMPDIR",
            "/tmp",
            "--setenv",
            "PATH",
            ":".join((*path_entries, "/usr/local/bin", "/usr/bin", "/bin")),
            "/usr/bin/setpriv",
            f"--reuid={agent_uid}",
            f"--regid={agent_gid}",
            "--clear-groups",
            "--bounding-set=-all",
            "--inh-caps=-all",
            "--ambient-caps=-all",
            f"/opt/codex/{native_relative.as_posix()}",
            "exec",
            "--ephemeral",
            "--json",
            "--ignore-user-config",
            "--disable",
            "plugins",
            "--disable",
            "remote_plugin",
            "--dangerously-bypass-approvals-and-sandbox",
            "--model",
            model,
            "-c",
            f'model_reasoning_effort="{effort}"',
            "-C",
            workspace.as_posix(),
            prompt,
        )
    )
    return command, mounts


def _resource_unit_name(output: Path, run_id: str) -> str:
    identity = hashlib.sha256(output.as_posix().encode()).hexdigest()[:10]
    return f"rtl-ass-eval-{identity}-{run_id}"


def _resource_command(command: list[str], unit: str, policy: ResourcePolicy, *, timeout: int) -> list[str]:
    return [
        "sudo",
        "-n",
        "systemd-run",
        "--wait",
        "--collect",
        "--pipe",
        "--quiet",
        f"--unit={unit}",
        "--property=MemoryAccounting=yes",
        f"--property=MemoryHigh={policy.memory_high_bytes}",
        f"--property=MemoryMax={policy.memory_max_bytes}",
        f"--property=MemorySwapMax={policy.memory_swap_max_bytes}",
        "--property=OOMPolicy=kill",
        "--property=CPUAccounting=yes",
        f"--property=CPUQuota={policy.cpu_quota_percent}%",
        "--property=TasksAccounting=yes",
        f"--property=TasksMax={policy.tasks_max}",
        "--property=KillMode=control-group",
        f"--property=RuntimeMaxSec={timeout + policy.runtime_grace_seconds}",
        "--",
        *command,
    ]


@contextlib.contextmanager
def _resource_lock() -> Iterator[float]:
    started = time.monotonic()
    with RESOURCE_LOCK.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield round(time.monotonic() - started, 3)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _systemd_control_group(unit: str) -> Path | None:
    result = subprocess.run(
        [
            "sudo",
            "-n",
            "systemctl",
            "show",
            f"{unit}.service",
            "--property=ControlGroup",
            "--value",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    value = result.stdout.strip()
    if result.returncode != 0 or not value.startswith("/"):
        return None
    path = Path("/sys/fs/cgroup") / value.lstrip("/")
    return path if path.is_dir() else None


def _integer_file(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, OSError, ValueError):
        return None


def _key_value_file(path: Path) -> dict[str, int]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return {}
    result: dict[str, int] = {}
    for line in lines:
        fields = line.split()
        if len(fields) == 2 and fields[1].isdigit():
            result[fields[0]] = int(fields[1])
    return result


def _host_available_memory() -> int | None:
    try:
        lines = Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return None
    for line in lines:
        fields = line.split()
        if len(fields) >= 2 and fields[0] == "MemAvailable:" and fields[1].isdigit():
            return int(fields[1]) * 1024
    return None


def _kill_resource_unit(unit: str) -> None:
    subprocess.run(
        [
            "sudo",
            "-n",
            "systemctl",
            "kill",
            "--kill-whom=all",
            "--signal=SIGKILL",
            f"{unit}.service",
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
    )


def _resource_preflight(policy: ResourcePolicy) -> dict[str, Any]:
    missing = [name for name in ("bwrap", "sudo", "systemctl", "systemd-run") if shutil.which(name) is None]
    if missing:
        raise RuntimeError(f"resource-supervised outer isolation requires commands: {', '.join(missing)}")
    sudo = subprocess.run(
        ["sudo", "-n", "true"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10
    )
    if sudo.returncode != 0:
        raise RuntimeError("resource-supervised outer isolation requires non-interactive sudo")
    resolver = Path("/run/systemd/resolve/stub-resolv.conf")
    if not resolver.is_file():
        raise RuntimeError("outer isolation requires the systemd-resolved stub file")
    controllers_path = Path("/sys/fs/cgroup/cgroup.controllers")
    controllers = set(controllers_path.read_text(encoding="utf-8").split()) if controllers_path.is_file() else set()
    required_controllers = {"cpu", "memory", "pids"}
    if not required_controllers.issubset(controllers):
        raise RuntimeError("resource-supervised outer isolation requires cgroup v2 cpu, memory, and pids controllers")
    available = _host_available_memory()
    required_available = policy.host_available_kill_bytes + policy.memory_max_bytes
    if available is None or available < required_available:
        raise RuntimeError(
            f"host available memory is below the audited start floor ({required_available} bytes required)"
        )
    if not RESOURCE_LOCK.parent.is_dir():
        raise RuntimeError(f"resource lock directory is unavailable: {RESOURCE_LOCK.parent}")
    return {
        "cgroup_version": 2,
        "controllers": sorted(controllers),
        "host_available_memory_bytes": available,
        "required_start_available_memory_bytes": required_available,
        "global_lock": RESOURCE_LOCK.as_posix(),
    }


def _monitor_resources(
    *,
    unit: str,
    policy: ResourcePolicy,
    telemetry_path: Path,
    stop: threading.Event,
    state: dict[str, Any],
) -> None:
    control_group: Path | None = None
    discovery_deadline = time.monotonic() + 10
    while not stop.is_set() and time.monotonic() < discovery_deadline:
        control_group = _systemd_control_group(unit)
        if control_group is not None:
            break
        stop.wait(0.1)
    state["control_group_observed"] = control_group is not None
    if control_group is None:
        return
    started = time.monotonic()
    peaks = {"memory_current": 0, "memory_peak": 0, "memory_swap_current": 0, "pids_current": 0}
    sample_count = 0
    with telemetry_path.open("w", encoding="utf-8") as output:
        while not stop.is_set():
            memory_current = _integer_file(control_group / "memory.current")
            memory_peak = _integer_file(control_group / "memory.peak")
            swap_current = _integer_file(control_group / "memory.swap.current")
            pids_current = _integer_file(control_group / "pids.current")
            host_available = _host_available_memory()
            memory_events = _key_value_file(control_group / "memory.events")
            sample = {
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "memory_current_bytes": memory_current,
                "memory_peak_bytes": memory_peak,
                "memory_swap_current_bytes": swap_current,
                "pids_current": pids_current,
                "cpu": _key_value_file(control_group / "cpu.stat"),
                "memory_events": memory_events,
                "host_available_memory_bytes": host_available,
            }
            if memory_events:
                state["last_memory_events"] = memory_events
                state["memory_events_observed"] = True
            output.write(json.dumps(sample, sort_keys=True) + "\n")
            output.flush()
            sample_count += 1
            for key, value in (
                ("memory_current", memory_current),
                ("memory_peak", memory_peak),
                ("memory_swap_current", swap_current),
                ("pids_current", pids_current),
            ):
                if value is not None:
                    peaks[key] = max(peaks[key], value)
            reason: str | None = None
            if memory_current is not None and memory_current >= policy.memory_kill_bytes:
                reason = "cgroup-memory-kill-threshold"
            elif host_available is not None and host_available <= policy.host_available_kill_bytes:
                reason = "host-available-memory-floor"
            if reason is not None:
                state["termination_reason"] = reason
                _kill_resource_unit(unit)
                break
            stop.wait(policy.sample_interval_seconds)
    state["samples"] = sample_count
    state["peaks"] = {f"{key}_bytes" if key != "pids_current" else key: value for key, value in peaks.items()}


def _monitor_transport(
    *,
    unit: str,
    trace_path: Path,
    policy: TransportPolicy,
    stop: threading.Event,
    state: dict[str, Any],
) -> None:
    started = time.monotonic()
    network_error_started: float | None = None
    state["monitor_started"] = True
    with trace_path.open("r", encoding="utf-8") as trace:
        while not stop.is_set():
            line = trace.readline()
            if line:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event_type = event.get("type")
                is_network_error = _network_error_message(event) is not None
                if is_network_error:
                    state["network_error_count"] = int(state.get("network_error_count", 0)) + 1
                    if network_error_started is None:
                        network_error_started = time.monotonic()
                        state["network_error_started_seconds"] = round(network_error_started - started, 3)
                elif event_type != "error":
                    network_error_started = None
                    state["last_progress_seconds"] = round(time.monotonic() - started, 3)
                continue
            if (
                network_error_started is not None
                and time.monotonic() - network_error_started >= policy.network_stall_seconds
            ):
                state["termination_reason"] = "network-stall"
                _kill_resource_unit(unit)
                break
            stop.wait(policy.sample_interval_seconds)
    state["monitor_thread_stopped"] = True


def _network_infrastructure_failure(trace: Mapping[str, Any], *, return_code: int, timed_out: bool) -> bool:
    return bool(trace.get("terminal_network_error")) and (return_code != 0 or timed_out)


def _run_one(
    *,
    executable: str,
    model: str,
    effort: str,
    sandbox: str,
    sandbox_network: bool,
    outer_bwrap: bool,
    timeout: int,
    output: Path,
    replicate: int,
    condition: str,
    case: WorkflowCase,
    skill_root: Path,
    ablation: str,
    retrieval_pack: Path | None,
) -> dict[str, Any]:
    run_id = f"pair-{replicate:02d}-{condition}"
    run_root = output / "runs" / run_id
    workspace = run_root / "workspace"
    run_root.mkdir(parents=True)
    initial = _prepare_workspace(
        workspace,
        condition,
        case,
        skill_root=skill_root,
        ablation=ablation,
        retrieval_pack=retrieval_pack,
    )
    retrieval_database = workspace / ".rtl-ass" / "eval.db"
    expected_retrieval_database_hash = hash_file(retrieval_database) if ablation == "retrieval" else None
    trace_path = run_root / "trace.raw.jsonl"
    stderr_path = run_root / "codex.stderr.txt"
    environment = os.environ.copy()
    original_codex_home = Path(environment.get("CODEX_HOME", Path.home() / ".codex")).resolve()
    auth_source = original_codex_home / "auth.json"
    if not auth_source.is_file() and "CODEX_API_KEY" not in environment:
        raise RuntimeError("Codex authentication is unavailable for the evaluation")
    disabled_skills: list[Path] = []
    outer_mounts: list[dict[str, str]] = []
    codex_home: Path | None = None
    if outer_bwrap:
        if not auth_source.is_file():
            raise RuntimeError("outer bwrap requires auth.json in CODEX_HOME")
        codex_home = run_root / "codex-home"
        codex_home.mkdir()
        temporary_directory = run_root / "tmp"
        temporary_directory.mkdir(mode=0o700)
        shutil.copy2(auth_source, codex_home / "auth.json")
        command, outer_mounts = _outer_bwrap_command(
            executable=executable,
            workspace=workspace,
            codex_home=codex_home,
            temporary_directory=temporary_directory,
            model=model,
            effort=effort,
            prompt=case.prompt,
        )
    else:
        disabled_skills = _disabled_host_skill_paths(original_codex_home)
        command = [
            executable,
            "exec",
            "--ephemeral",
            "--json",
            "--ignore-user-config",
            "--disable",
            "plugins",
            "--disable",
            "remote_plugin",
            "--sandbox",
            sandbox,
            "--model",
            model,
            "-c",
            f'model_reasoning_effort="{effort}"',
            "-c",
            _skills_config_override(disabled_skills),
            *(["-c", "sandbox_workspace_write.network_access=true"] if sandbox_network else []),
            "-C",
            str(workspace),
            case.prompt,
        ]
    environment.pop("PYTHONPATH", None)
    started_at = datetime.now(UTC).isoformat()
    started_monotonic = time.monotonic()
    timed_out = False
    stderr_raw_path = run_root / "codex.stderr.raw.txt"
    telemetry_path = run_root / "resource-telemetry.jsonl"
    resource_policy = DEFAULT_RESOURCE_POLICY if outer_bwrap else None
    transport_policy = DEFAULT_TRANSPORT_POLICY if outer_bwrap else None
    resource_unit = _resource_unit_name(output, run_id) if resource_policy is not None else None
    execution_command = (
        _resource_command(command, resource_unit, resource_policy, timeout=timeout)
        if resource_policy is not None and resource_unit is not None
        else command
    )
    resource_state: dict[str, Any] = {}
    transport_state: dict[str, Any] = {}
    resource_stop = threading.Event()
    resource_thread: threading.Thread | None = None
    transport_thread: threading.Thread | None = None
    lock_context = _resource_lock() if resource_policy is not None else contextlib.nullcontext(0.0)
    with lock_context as lock_wait_seconds:
        with (
            trace_path.open("w", encoding="utf-8") as trace_output,
            stderr_raw_path.open("w", encoding="utf-8") as stderr_output,
        ):
            process = subprocess.Popen(
                execution_command,
                stdout=trace_output,
                stderr=stderr_output,
                stdin=subprocess.DEVNULL,
                text=True,
                env=environment,
                start_new_session=True,
            )
            if resource_policy is not None and resource_unit is not None:
                resource_thread = threading.Thread(
                    target=_monitor_resources,
                    kwargs={
                        "unit": resource_unit,
                        "policy": resource_policy,
                        "telemetry_path": telemetry_path,
                        "stop": resource_stop,
                        "state": resource_state,
                    },
                    name=f"resource-monitor-{run_id}",
                    daemon=True,
                )
                resource_thread.start()
                if transport_policy is not None:
                    transport_thread = threading.Thread(
                        target=_monitor_transport,
                        kwargs={
                            "unit": resource_unit,
                            "trace_path": trace_path,
                            "policy": transport_policy,
                            "stop": resource_stop,
                            "state": transport_state,
                        },
                        name=f"transport-monitor-{run_id}",
                        daemon=True,
                    )
                    transport_thread.start()
            try:
                process.wait(timeout=timeout)
                return_code = process.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                return_code = 124
                if resource_unit is not None:
                    _kill_resource_unit(resource_unit)
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=30)
            except BaseException:
                if resource_unit is not None:
                    _kill_resource_unit(resource_unit)
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                raise
            finally:
                resource_stop.set()
                if resource_thread is not None:
                    resource_thread.join(timeout=5)
                    resource_state["monitor_thread_stopped"] = not resource_thread.is_alive()
                if transport_thread is not None:
                    transport_thread.join(timeout=5)
                    transport_state["monitor_thread_stopped"] = not transport_thread.is_alive()
    finished_at = datetime.now(UTC).isoformat()
    duration_seconds = round(time.monotonic() - started_monotonic, 3)
    stderr = stderr_raw_path.read_text(encoding="utf-8", errors="replace")
    stderr_path.write_text(_redact(stderr, workspace), encoding="utf-8")
    stderr_raw_path.unlink()
    trace = _parse_trace(trace_path, workspace, skill_root)
    observable_text = "\n".join(trace["agent_messages"]) + "\n" + stderr
    memory_events = resource_state.get("last_memory_events", {})
    resource_monitor_failure = resource_policy is not None and (
        not resource_state.get("control_group_observed")
        or not resource_state.get("samples")
        or not resource_state.get("memory_events_observed")
        or not resource_state.get("monitor_thread_stopped")
    )
    resource_limit_hit = bool(resource_state.get("termination_reason")) or (
        isinstance(memory_events, dict)
        and any(int(memory_events.get(key, 0)) > 0 for key in ("max", "oom", "oom_kill", "oom_group_kill"))
    )
    transport_monitor_failure = transport_policy is not None and (
        not transport_state.get("monitor_started") or not transport_state.get("monitor_thread_stopped")
    )
    transport_failure = bool(transport_state.get("termination_reason")) or _network_infrastructure_failure(
        trace, return_code=return_code, timed_out=timed_out
    )
    infrastructure_failure = (
        resource_monitor_failure
        or resource_limit_hit
        or transport_monitor_failure
        or transport_failure
        or (return_code != 0 and not timed_out)
        or any(
            marker in observable_text
            for marker in ("Failed RTM_NEWADDR", "sandbox failure", "execution sandbox", "bwrap:")
        )
    )
    agent_evidence = _workspace_evidence(workspace)
    grade = _grade(workspace, run_root, initial, case)
    expected_subjects = grade.get("expected_agent_evidence_subjects")
    current_passed_evidence_kinds = (
        _current_passed_evidence_kinds(agent_evidence, expected_subjects=expected_subjects)
        if isinstance(expected_subjects, dict)
        else []
    )
    workflow_audit = _workflow_audit(trace, case, condition, grade, ablation=ablation)
    workflow_efficiency = _workflow_efficiency(trace, agent_evidence)
    knowledge_retrieval = _workspace_retrieval(
        workspace,
        trace,
        expected_database_hash=expected_retrieval_database_hash,
    )
    result = {
        "schema_version": "1.0",
        "run_id": run_id,
        "case": case.identifier,
        "replicate": replicate,
        "condition": condition,
        "ablation": ablation,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": duration_seconds,
        "codex_return_code": return_code,
        "timed_out": timed_out,
        "infrastructure_failure": infrastructure_failure,
        "resource_limit_hit": resource_limit_hit,
        "resource_monitor_failure": resource_monitor_failure,
        "transport_failure": transport_failure,
        "transport_monitor_failure": transport_monitor_failure,
        "resource_supervision": (
            {
                "unit": resource_unit,
                "global_lock_wait_seconds": lock_wait_seconds,
                "policy": asdict(resource_policy),
                "telemetry": resource_state,
                "telemetry_file": telemetry_path.name if telemetry_path.is_file() else None,
                "telemetry_file_hash": hash_file(telemetry_path) if telemetry_path.is_file() else None,
            }
            if resource_policy is not None
            else None
        ),
        "transport_supervision": (
            {"policy": asdict(transport_policy), "telemetry": transport_state} if transport_policy is not None else None
        ),
        "disabled_host_skills": [_redact(path.as_posix(), workspace) for path in disabled_skills],
        "outer_bwrap": outer_bwrap,
        "outer_mounts": _redact_value(outer_mounts, workspace),
        "initial": initial,
        "trace_file_hash": hash_file(trace_path),
        "stderr_file_hash": hash_file(stderr_path),
        "trace": trace,
        "agent_evidence": agent_evidence,
        "agent_evidence_kinds": sorted(
            {item["kind"] for item in agent_evidence if item.get("valid_json") and isinstance(item.get("kind"), str)}
        ),
        "current_passed_evidence_kinds": current_passed_evidence_kinds,
        "workflow_audit": workflow_audit,
        "workflow_efficiency": workflow_efficiency,
        "knowledge_retrieval": knowledge_retrieval,
        "grade": _redact_value(grade, workspace),
    }
    result["deliverable_complete"] = bool(grade.get("complete", grade.get("correct")))
    result["task_success"] = (
        not infrastructure_failure and not timed_out and return_code == 0 and result["deliverable_complete"]
    )
    if codex_home is not None:
        shutil.rmtree(codex_home)
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
        workflow_compliant = sum(bool(item.get("workflow_audit", {}).get("compliant", True)) for item in valid_items)
        workflow_efficient = sum(
            bool(item.get("workflow_efficiency", {}).get("efficient", True)) for item in valid_items
        )
        retrievals = [item.get("knowledge_retrieval", {}) for item in valid_items]
        complete_commands = sum(required.issubset(item["trace"]["executed_evidence_kinds"]) for item in valid_items)
        structured_evidence = sum(required.issubset(item["current_passed_evidence_kinds"]) for item in valid_items)
        input_usage = [item["trace"]["usage"].get("input_tokens") for item in valid_items]
        output_usage = [item["trace"]["usage"].get("output_tokens") for item in valid_items]
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
            "workflow_compliant_runs": workflow_compliant,
            "workflow_violation_runs": valid - workflow_compliant,
            "workflow_efficient_runs": workflow_efficient,
            "workflow_efficiency_finding_runs": valid - workflow_efficient,
            "redundant_evidence_executions": sum(
                int(item.get("workflow_efficiency", {}).get("redundant_evidence_execution_count", 0))
                for item in valid_items
            ),
            "post_ready_eda_commands": sum(
                len(item.get("workflow_efficiency", {}).get("post_ready_eda_commands", [])) for item in valid_items
            ),
            "valid_retrieval_receipts": sum(int(retrieval.get("valid_receipt_count", 0)) for retrieval in retrievals),
            "runs_with_valid_retrieval": sum(
                int(retrieval.get("valid_receipt_count", 0)) > 0 for retrieval in retrievals
            ),
            "retrieval_results_returned": sum(
                len(retrieval.get("returned_result_ids", [])) for retrieval in retrievals
            ),
            "retrieval_results_inspected": sum(
                len(retrieval.get("inspected_result_ids", [])) for retrieval in retrievals
            ),
            "retrieval_results_uninspected": sum(
                len(retrieval.get("uninspected_result_ids", [])) for retrieval in retrievals
            ),
            "complete_evidence_commands": complete_commands,
            "complete_structured_evidence": structured_evidence,
            "structured_evidence_wilson_95": _wilson_interval(structured_evidence, valid),
            "usage_complete_runs": sum(
                isinstance(input_value, int) and isinstance(output_value, int)
                for input_value, output_value in zip(input_usage, output_usage, strict=True)
            ),
            "input_tokens": (sum(input_usage) if all(isinstance(value, int) for value in input_usage) else None),
            "output_tokens": (sum(output_usage) if all(isinstance(value, int) for value in output_usage) else None),
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


def _print_run_result(result: Mapping[str, Any]) -> None:
    print(
        json.dumps(
            {
                "run_id": result["run_id"],
                "return_code": result["codex_return_code"],
                "task_success": result["task_success"],
                "candidate_correct": result["grade"].get("correct", False),
                "deliverable_complete": result["deliverable_complete"],
                "workflow_compliant": result["workflow_audit"]["compliant"],
                "resource_limit_hit": result["resource_limit_hit"],
                "transport_failure": result["transport_failure"],
            },
            sort_keys=True,
        ),
        flush=True,
    )


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replicates", type=int, default=5)
    parser.add_argument("--parallel", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--effort", choices=REASONING_EFFORTS, default="high")
    parser.add_argument(
        "--sandbox-network",
        action="store_true",
        help="allow command network access when the host cannot initialize Codex's isolated loopback namespace",
    )
    parser.add_argument(
        "--outer-bwrap",
        action="store_true",
        help="run Codex without its inner sandbox inside a root-created, capability-dropped bwrap boundary",
    )
    parser.add_argument(
        "--skill-root",
        type=Path,
        default=SKILL_ROOT,
        help="Skill payload copied into the on condition; use an extracted release archive for release claims",
    )
    parser.add_argument(
        "--ablation",
        choices=("skill", "retrieval"),
        default="skill",
        help="compare Skill absence/presence or compare an empty/non-empty audited retrieval index",
    )
    parser.add_argument(
        "--retrieval-pack",
        type=Path,
        help="portable knowledge pack imported only for the retrieval-on condition",
    )
    parser.add_argument("--case", choices=sorted(CASES), default=DEFAULT_CASE_ID)
    args = parser.parse_args(arguments)
    if not 1 <= args.replicates <= 20 or not 1 <= args.parallel <= 4 or not 60 <= args.timeout <= 3600:
        raise SystemExit("replicates, parallelism, or timeout is outside the audited range")
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing to reuse output directory: {output}")
    output.mkdir(parents=True)
    skill_root = args.skill_root.resolve()
    required_skill_files = (skill_root / "SKILL.md", skill_root / "scripts" / "rtl_ass.py")
    if not skill_root.is_dir() or not all(path.is_file() and not path.is_symlink() for path in required_skill_files):
        raise SystemExit("skill root is missing a regular SKILL.md or scripts/rtl_ass.py")
    retrieval_pack = args.retrieval_pack.resolve() if args.retrieval_pack is not None else None
    if (args.ablation == "retrieval") != (retrieval_pack is not None):
        raise SystemExit("--ablation retrieval requires --retrieval-pack, which is forbidden for skill ablation")
    if retrieval_pack is not None and (not retrieval_pack.is_file() or retrieval_pack.is_symlink()):
        raise SystemExit("retrieval pack must be a regular non-symlink file")
    if args.outer_bwrap and args.sandbox_network:
        raise SystemExit("--sandbox-network only configures Codex's inner workspace-write sandbox")
    if args.outer_bwrap and args.parallel != 1:
        raise SystemExit("resource-supervised --outer-bwrap requires --parallel 1")
    resource_preflight = _resource_preflight(DEFAULT_RESOURCE_POLICY) if args.outer_bwrap else None
    codex_version = _codex_version(args.codex)
    case = get_case(args.case)
    retrieval_contamination_audit = (
        _validate_retrieval_ablation_pack(retrieval_pack, case) if retrieval_pack is not None else None
    )
    jobs: list[tuple[int, str]] = [
        (replicate, condition)
        for replicate in range(1, args.replicates + 1)
        for condition in (("off", "on") if replicate % 2 else ("on", "off"))
    ]
    results: list[dict[str, Any]] = []
    run_arguments = [
        {
            "executable": args.codex,
            "model": args.model,
            "effort": args.effort,
            "sandbox": "workspace-write",
            "sandbox_network": args.sandbox_network,
            "outer_bwrap": args.outer_bwrap,
            "timeout": args.timeout,
            "output": output,
            "replicate": replicate,
            "condition": condition,
            "case": case,
            "skill_root": skill_root,
            "ablation": args.ablation,
            "retrieval_pack": retrieval_pack,
        }
        for replicate, condition in jobs
    ]
    if args.parallel == 1:
        for run_argument in run_arguments:
            result = _run_one(**run_argument)
            results.append(result)
            _print_run_result(result)
            if args.outer_bwrap and result["infrastructure_failure"]:
                print(
                    json.dumps(
                        {
                            "campaign_aborted": True,
                            "reason": "infrastructure_failure",
                            "run_id": result["run_id"],
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
                return 2
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as executor:
            futures = [
                executor.submit(
                    _run_one,
                    **run_argument,
                )
                for run_argument in run_arguments
            ]
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                results.append(result)
                _print_run_result(result)
    results.sort(key=lambda item: (item["replicate"], item["condition"]))
    report = {
        "schema_version": "1.0",
        "kind": "codex-skill-workflow-audit",
        "generated_at": datetime.now(UTC).isoformat(),
        "case": case.identifier,
        "ablation": args.ablation,
        "retrieval_pack_hash": hash_file(retrieval_pack) if retrieval_pack is not None else None,
        "retrieval_pack_tree_hash": _hash_tree(retrieval_pack.parent) if retrieval_pack is not None else None,
        "retrieval_contamination_audit": retrieval_contamination_audit,
        "prompt_hash": hashlib.sha256(case.prompt.encode()).hexdigest(),
        "fixture_hash": _hash_tree(case.public_fixture),
        "hidden_grader_hash": _hash_tree(case.public_fixture.parent / "private"),
        "harness_hash": _hash_files((Path(__file__).resolve(), ROOT / "evals" / "workflow_cases.py")),
        "skill_hash": _hash_tree(skill_root),
        "runtime_hash": _hash_tree(
            skill_root / "runtime" if (skill_root / "runtime").is_dir() else ROOT / "src" / "rtl_ass"
        ),
        "skill_delivery": "embedded-release" if (skill_root / "runtime").is_dir() else "source-tree",
        "codex_version": codex_version,
        "model": args.model,
        "reasoning_effort": args.effort,
        "sandbox": "outer-bwrap+inner-danger-full-access" if args.outer_bwrap else "workspace-write",
        "sandbox_network_access": args.sandbox_network or args.outer_bwrap,
        "outer_bwrap": args.outer_bwrap,
        "resource_supervision": (
            {"policy": asdict(DEFAULT_RESOURCE_POLICY), "preflight": resource_preflight} if args.outer_bwrap else None
        ),
        "transport_supervision": ({"policy": asdict(DEFAULT_TRANSPORT_POLICY)} if args.outer_bwrap else None),
        "outer_isolation": (
            {
                "host_uid_before_drop": 0,
                "agent_uid": os.getuid(),
                "agent_gid": os.getgid(),
                "capability_bounding_set": "empty",
                "pid_namespace": "isolated",
                "network_namespace": "shared",
                "workspace_mount": "read-write",
                "codex_package_and_open_tool_mounts": "read-only",
                "host_repository_mounted": False,
                "private_grader_mounted": False,
            }
            if args.outer_bwrap
            else None
        ),
        "replicates": args.replicates,
        "required_evidence": sorted(case.required_evidence),
        "allowed_evidence": sorted(case.allowed_evidence),
        "tool_discovery": _redact_host_value(discover_tools()),
        "trace_policy": {
            "raw_jsonl_local_only": True,
            "reasoning_content_retained_in_sanitized_results": False,
            "observable_items": ["agent_message", "command_execution", "file_change", "usage"],
            "workflow_command_findings": [
                "network-command",
                "package-network-command",
                "proprietary-tool-command",
                "nested-agent-command",
            ],
            "opaque_generated_program_behavior_inferred": False,
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
