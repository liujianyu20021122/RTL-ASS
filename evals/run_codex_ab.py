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
from rtl_ass.kb.gates import validate_run_evidence, validate_verification_gate
from rtl_ass.kb.models import RecordRole, RecordStatus
from rtl_ass.kb.retrieval import build_retrieval_receipt, validate_retrieval_receipt
from rtl_ass.tools import discover_tools
from rtl_ass.waveform import validate_waveform_evidence

if __package__:
    from .knowledge_application import audit_application
    from .retrieval_treatment import validate_retrieval_treatment
    from .soc_workflow_cases import SOC_CASES, materialize_soc_case
    from .workflow_cases import CASES, WorkflowCase, get_case
else:
    # Direct-file execution places evals/ rather than the repository root on
    # sys.path. Keep that supported because the documented audit command uses
    # this file directly; module execution continues to use the package import.
    from knowledge_application import audit_application  # type: ignore[import-not-found,no-redef]
    from retrieval_treatment import validate_retrieval_treatment  # type: ignore[import-not-found,no-redef]
    from soc_workflow_cases import (  # type: ignore[import-not-found,no-redef]
        SOC_CASES,
        materialize_soc_case,
    )
    from workflow_cases import CASES, WorkflowCase, get_case  # type: ignore[import-not-found,no-redef]

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / ".agents" / "skills" / "rtl-ass"
DEFAULT_CASE_ID = "repair-non-power-of-two-fifo"
REASONING_EFFORTS = ("none", "low", "medium", "high", "xhigh", "max")
KNOWLEDGE_TREATMENT_ABLATIONS = frozenset({"product", "retrieval"})
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
When lint is required, do not demote warnings to force a zero exit status; resolve them unless the supplied
repository policy contains an explicit reviewed waiver.
Generated evidence may be written under artifacts/. Do not commit changes.
"""
RETRIEVAL_AGENT_RULES = """
An approved evaluation index is available at `.rtl-ass/eval.db` in namespace `eval:retrieval`.
When relevant, search that namespace for `promoted` records first and then `verified` records only when no
promoted result applies. Use explicit `--match any --limit 3 --actor codex --output <distinct-receipt>`, retain every
receipt, and inspect at most three selected records with `kb show <id> --include-content`. Never use `raw` or
`candidate` records as coding guidance. The index is advisory and may be empty.
Do not invoke an RTL-ASS EDA adapter in this retrieval comparison. Preserve the task's direct or project-local
open-source verification flow; adapter fallback authorization is evaluated separately.
"""
RETRIEVAL_ABLATION_ROLES = frozenset({"design-pattern", "verification-pattern", "rtl-design"})


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


def _validate_retrieval_ablation_database(path: Path, case: WorkflowCase) -> dict[str, Any]:
    """Require a small audited database of calibrated, contamination-reviewed cards."""
    if not path.is_file() or path.is_symlink():
        raise RtlAssError("unsafe_retrieval_ablation", "retrieval database must be a regular file")
    database = KnowledgeDatabase(path)
    audit = database.verify_audit_chain()
    if not audit["valid"]:
        raise RtlAssError("unsafe_retrieval_ablation", "retrieval database audit chain is invalid")
    case_hashes = {
        hash_file(candidate)
        for root in (case.public_fixture, case.public_fixture.parent / "private")
        for candidate in root.rglob("*")
        if candidate.is_file() and not candidate.is_symlink()
    }
    try:
        with contextlib.closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT id, namespace, role, status, content_hash, source_path,
                       license_status, metadata_json
                FROM records
                ORDER BY id
                """
            ).fetchall()
    except sqlite3.Error as exc:
        raise RtlAssError("unsafe_retrieval_ablation", "retrieval database cannot be inspected") from exc

    cards = [row for row in rows if row["role"] in RETRIEVAL_ABLATION_ROLES]
    other_records = [row for row in rows if row["role"] not in RETRIEVAL_ABLATION_ROLES]
    if any(row["namespace"] != "eval:retrieval" for row in rows):
        raise RtlAssError("unsafe_retrieval_ablation", "retrieval database contains another namespace")
    if not 1 <= len(cards) <= 3:
        raise RtlAssError("unsafe_retrieval_ablation", "retrieval database requires 1-3 calibrated cards")
    if any(row["role"] != "tool-evidence" or row["status"] != "candidate" for row in other_records):
        raise RtlAssError(
            "unsafe_retrieval_ablation",
            "retrieval database may contain only calibrated cards and candidate tool-evidence records",
        )
    reviewed_hashes: list[str] = []
    record_ids: list[str] = []
    statuses: list[str] = []
    for record in cards:
        try:
            metadata = json.loads(record["metadata_json"])
        except (json.JSONDecodeError, TypeError) as exc:
            raise RtlAssError("unsafe_retrieval_ablation", "retrieval card metadata is invalid") from exc
        if (
            record["namespace"] != "eval:retrieval"
            or record["status"] not in {"verified", "promoted"}
            or record["license_status"] != "known"
            or record["content_hash"] in case_hashes
            or record["source_path"].startswith("evals/workflow_cases/")
            or not isinstance(metadata, dict)
            or metadata.get("contamination_review") != "no-task-source-no-test-no-reference-no-patch-no-grader-output"
        ):
            raise RtlAssError(
                "unsafe_retrieval_ablation",
                "retrieval database contains an uncalibrated, unreviewed, or task-identical card",
                {"record": record["id"]},
            )
        stored = database.get_record(record["id"])
        verification = stored.get("verification")
        if not isinstance(verification, dict):
            raise RtlAssError("unsafe_retrieval_ablation", "calibrated card is missing its verification gate")
        validate_verification_gate(
            verification,
            record["content_hash"],
            verification.get("required_kinds", []),
        )
        reviewed_hashes.append(record["content_hash"])
        record_ids.append(record["id"])
        statuses.append(record["status"])
    return {
        "status": "pass",
        "policy_version": "2.0",
        "database_hash": hash_file(path),
        "audit_chain": audit,
        "record_count": len(cards),
        "record_ids": record_ids,
        "record_statuses": statuses,
        "record_content_hashes": reviewed_hashes,
        "case_artifact_hash_count": len(case_hashes),
        "direct_hash_overlap": False,
        "allowed_roles": sorted(RETRIEVAL_ABLATION_ROLES),
        "semantic_review_marker_required": True,
        "boundary": (
            "the audit chain and calibrated lifecycle are machine-checked; semantic absence of answer content remains "
            "an explicit human review assertion"
        ),
    }


def _retrieval_case_identity(case: WorkflowCase) -> dict[str, str]:
    return {
        "case_id": case.identifier,
        "prompt_hash": hashlib.sha256(case.prompt.encode()).hexdigest(),
        "fixture_hash": _hash_tree(case.public_fixture),
        "hidden_grader_hash": _hash_tree(case.public_fixture.parent / "private"),
    }


def _load_retrieval_treatment(
    path: Path,
    *,
    case: WorkflowCase,
    database_audit: Mapping[str, Any],
) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise RtlAssError("invalid_retrieval_treatment", "retrieval treatment must be a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RtlAssError("invalid_retrieval_treatment", "retrieval treatment must be one UTF-8 JSON object") from exc
    hashes = database_audit.get("record_content_hashes")
    if not isinstance(hashes, list) or not all(isinstance(item, str) for item in hashes):
        raise RtlAssError("invalid_retrieval_treatment", "retrieval database audit is missing card identities")
    return validate_retrieval_treatment(
        value,
        expected_case_identity=_retrieval_case_identity(case),
        calibrated_record_hashes=hashes,
    )


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
    retrieval_database: Path | None = None,
) -> dict[str, str]:
    selected_case = case or get_case(DEFAULT_CASE_ID)
    if condition not in {"off", "on"}:
        raise ValueError(f"unknown evaluation condition: {condition}")
    if workspace.exists():
        raise RuntimeError(f"refusing to reuse evaluation workspace: {workspace}")
    if ablation not in {"skill", *KNOWLEDGE_TREATMENT_ABLATIONS}:
        raise ValueError(f"unknown ablation: {ablation}")
    if (ablation in KNOWLEDGE_TREATMENT_ABLATIONS) != (retrieval_database is not None):
        raise ValueError("knowledge treatment requires exactly one calibrated knowledge database")
    if retrieval_database is not None:
        _validate_retrieval_ablation_database(retrieval_database, selected_case)
    shutil.copytree(selected_case.public_fixture, workspace)
    initial = {
        path.relative_to(workspace).as_posix(): hash_file(path)
        for path in sorted(item for item in workspace.rglob("*") if item.is_file() and not item.is_symlink())
    }
    treatment_visible = ablation == "retrieval" or (ablation == "product" and condition == "on")
    agent_rules = AGENT_RULES + (RETRIEVAL_AGENT_RULES if treatment_visible else "")
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
    if treatment_visible:
        database_path = workspace / ".rtl-ass" / "eval.db"
        database_path.parent.mkdir(parents=True, exist_ok=True)
        if condition == "on" and retrieval_database is not None:
            shutil.copyfile(retrieval_database, database_path)
        else:
            KnowledgeDatabase(database_path).initialize(actor="evaluation-harness")
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
    for raw_segment in _expanded_command_segments(command):
        segment = _normalized_command_segment(raw_segment)
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


def _rtl_ass_eda_adapter_kinds(command: str) -> set[str]:
    """Return external EDA classes requested through RTL-ASS, including failed attempts."""
    verify_kinds = {
        "lint": "lint",
        "simulate": "simulation",
        "formal": "formal",
        "synth": "synthesis",
        "equiv": "equivalence",
        "sta": "sta",
    }
    kinds: set[str] = set()
    for segment in _expanded_command_segments(command):
        arguments = _rtl_ass_arguments(segment)
        if arguments is None or len(arguments) < 2:
            continue
        if arguments[0] == "verify" and arguments[1] in verify_kinds:
            kinds.add(verify_kinds[arguments[1]])
        elif arguments[:2] in (["wave", "query"], ["wave", "diff"]):
            waveform = next((value for value in arguments[2:] if not value.startswith("-")), "")
            if Path(waveform).suffix.lower() == ".fst":
                kinds.add("waveform")
    return kinds


def _command_segments(command: str) -> list[list[str]]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        return []
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token and set(token).issubset({";", "&", "|", "\n"}):
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


def _normalized_command_segment(segment: Sequence[str]) -> list[str]:
    """Remove shell environment prefixes without changing the invoked argument vector."""
    result = list(segment)
    while result and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", result[0], flags=re.DOTALL):
        result.pop(0)
    if result and Path(result[0]).name == "env":
        result.pop(0)
        while result:
            if result[0] == "--":
                result.pop(0)
                break
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", result[0], flags=re.DOTALL):
                result.pop(0)
                continue
            if result[0] in {"-i", "--ignore-environment"}:
                result.pop(0)
                continue
            if result[0] in {"-u", "--unset"} and len(result) >= 2:
                del result[:2]
                continue
            if result[0].startswith("--unset="):
                result.pop(0)
                continue
            break
    return result


def _skill_command_signals(command: str, *, matching_skill: bool) -> set[str]:
    if not matching_skill:
        return set()
    signals: set[str] = set()
    readers = {"awk", "bat", "cat", "grep", "head", "less", "more", "nl", "rg", "sed", "tail"}
    segments = _expanded_command_segments(command)
    for raw_segment in segments:
        segment = _normalized_command_segment(raw_segment)
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
    for raw_segment in _expanded_command_segments(command):
        segment = _normalized_command_segment(raw_segment)
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
    workflow_mechanisms: Mapping[str, Any] | None = None,
    knowledge_retrieval: Mapping[str, Any] | None = None,
    retrieval_treatment: Mapping[str, Any] | None = None,
    knowledge_application: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    if case.requires_knowledge_usage:
        if knowledge_application is None or knowledge_application.get("status") != "audited":
            violations.append({"reason": "knowledge-use-declaration-missing-or-invalid"})
        elif any(item.get("outcome") == "unsupported" for item in knowledge_application.get("uses", [])):
            violations.append({"reason": "knowledge-use-claim-unsupported"})
        elif knowledge_application.get("unreported_read_ids"):
            violations.append({"reason": "knowledge-read-missing-use-declaration"})
    rtl_ass_eda_adapter_commands: list[dict[str, Any]] = []
    lint_warning_demotion_commands: list[dict[str, Any]] = []
    commands = trace.get("commands", [])
    if isinstance(commands, list):
        for index, item in enumerate(commands):
            if not isinstance(item, dict) or not isinstance(item.get("command"), str):
                continue
            for finding in _command_policy_findings(item["command"]):
                violations.append({"command_index": index, **finding})
            adapter_kinds = sorted(_rtl_ass_eda_adapter_kinds(item["command"]))
            if adapter_kinds:
                rtl_ass_eda_adapter_commands.append(
                    {
                        "command_index": index,
                        "evidence_kinds": adapter_kinds,
                        "status": item.get("status"),
                        "exit_code": item.get("exit_code"),
                    }
                )
            if "lint" in case.required_evidence:
                for segment in _expanded_command_segments(item["command"]):
                    normalized = _normalized_command_segment(segment)
                    if (
                        normalized
                        and Path(normalized[0]).name == "verilator"
                        and "--lint-only" in normalized[1:]
                        and {"-Wno-fatal", "--Wno-fatal"}.intersection(normalized[1:])
                    ):
                        lint_warning_demotion_commands.append(
                            {
                                "command_index": index,
                                "status": item.get("status"),
                                "exit_code": item.get("exit_code"),
                            }
                        )
                        break
    if lint_warning_demotion_commands:
        violations.append(
            {
                "reason": "required-lint-warning-demotion-forbidden",
                "command_indices": [item["command_index"] for item in lint_warning_demotion_commands],
            }
        )
    if ablation in KNOWLEDGE_TREATMENT_ABLATIONS and rtl_ass_eda_adapter_commands:
        comparison = "retrieval-ablation" if ablation == "retrieval" else "product-comparison"
        violations.append(
            {
                "reason": f"rtl-ass-eda-adapter-forbidden-in-{comparison}",
                "command_indices": [item["command_index"] for item in rtl_ass_eda_adapter_commands],
            }
        )
    if ablation in KNOWLEDGE_TREATMENT_ABLATIONS and knowledge_retrieval is not None:
        if ablation == "retrieval" and condition == "off":
            if int(knowledge_retrieval.get("valid_receipt_count", 0)) == 0:
                violations.append({"reason": "empty-control-retrieval-receipt-missing"})
        elif condition == "on":
            if int(knowledge_retrieval.get("calibrated_receipt_count", 0)) == 0:
                violations.append({"reason": "calibrated-retrieval-receipt-missing"})
            treatment_label = retrieval_treatment.get("treatment") if retrieval_treatment is not None else None
            calibrated_inspection_required = treatment_label != "plausible-irrelevant"
            if calibrated_inspection_required and not knowledge_retrieval.get("calibrated_inspected_result_ids"):
                violations.append({"reason": "calibrated-retrieval-result-not-inspected"})
    skill_signals = trace.get("skill_signals", [])
    if ablation in {"skill", "product"} and condition == "off" and skill_signals:
        violations.append({"reason": "skill-visible-in-off-condition"})
    protected = grade.get("protected_files_unchanged")
    if protected is False:
        violations.append({"reason": "protected-fixture-changed"})
    if trace.get("invalid_jsonl_lines"):
        violations.append({"reason": "invalid-trace-jsonl"})
    skill_available = ablation == "retrieval" or condition == "on"
    mechanisms = workflow_mechanisms or {}
    missing_mechanisms = sorted(
        mechanism for mechanism in case.skill_required_mechanisms if skill_available and not mechanisms.get(mechanism)
    )
    for mechanism in missing_mechanisms:
        violations.append({"reason": "required-skill-mechanism-missing", "mechanism": mechanism})
    executed = {value for value in trace.get("executed_evidence_kinds", []) if isinstance(value, str)}
    extra_evidence = sorted(executed - case.allowed_evidence)
    return {
        "policy_version": "1.6",
        "condition": condition,
        "ablation": ablation,
        "retrieval_treatment": (retrieval_treatment.get("treatment") if retrieval_treatment is not None else None),
        "calibrated_inspection_required": (
            condition == "on"
            and ablation in KNOWLEDGE_TREATMENT_ABLATIONS
            and (retrieval_treatment is None or retrieval_treatment.get("treatment") != "plausible-irrelevant")
        ),
        "skill_activated": bool(skill_signals),
        "allowed_evidence": sorted(case.allowed_evidence),
        "required_evidence": sorted(case.required_evidence),
        "required_skill_mechanisms": sorted(case.skill_required_mechanisms),
        "missing_required_skill_mechanisms": missing_mechanisms,
        "rtl_ass_eda_adapter_policy": ("forbidden" if ablation in KNOWLEDGE_TREATMENT_ABLATIONS else "case-prompt"),
        "rtl_ass_eda_adapter_commands": rtl_ass_eda_adapter_commands,
        "lint_warning_demotion_commands": lint_warning_demotion_commands,
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
    failed_rtl_ass_entrypoints: list[dict[str, Any]] = []
    if isinstance(commands, list):
        for index, item in enumerate(commands):
            if (
                isinstance(item, dict)
                and item.get("status") != "completed"
                and item.get("exit_code") == 127
                and isinstance(item.get("command"), str)
                and any(_is_bare_rtl_ass_invocation(segment) for segment in _expanded_command_segments(item["command"]))
            ):
                failed_rtl_ass_entrypoints.append({"command_index": index, "exit_code": 127})
            if ready_gate_index is None and _successful_ready_gate(item):
                ready_gate_index = index
                continue
            if ready_gate_index is None or not isinstance(item, dict) or not isinstance(item.get("command"), str):
                continue
            kinds = sorted(_command_kinds(item["command"]))
            if kinds:
                post_ready.append({"command_index": index, "evidence_kinds": kinds})
    return {
        "policy_version": "1.1",
        "duplicate_evidence_identities": duplicates,
        "redundant_evidence_execution_count": sum(len(item["paths"]) - 1 for item in duplicates),
        "successful_ready_gate_command_index": ready_gate_index,
        "post_ready_eda_commands": post_ready,
        "failed_rtl_ass_entrypoint_commands": failed_rtl_ass_entrypoints,
        "efficient": not duplicates and not post_ready and not failed_rtl_ass_entrypoints,
        "interpretation": (
            "efficiency diagnostics do not change candidate correctness, evidence validity, workflow compliance, "
            "or infrastructure attribution"
        ),
    }


def _workflow_mechanisms(trace: Mapping[str, Any], *, tracked_paths: Iterable[str] = ()) -> dict[str, Any]:
    """Summarize pre-registered, observable workflow mechanisms without inferring reasoning."""
    commands = trace.get("commands")
    command_items = [item for item in commands if isinstance(item, dict)] if isinstance(commands, list) else []
    first_change = trace.get("first_file_change_event_index")
    first_change_index = first_change if isinstance(first_change, int) else None
    tracked = set(tracked_paths)
    tracked_change_events = []
    raw_change_events = trace.get("file_change_events")
    if isinstance(raw_change_events, list):
        for item in raw_change_events:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            event_index = item.get("event_index")
            if not isinstance(path, str) or not isinstance(event_index, int):
                continue
            relative = path.removeprefix("$WORKSPACE/")
            if relative in tracked:
                tracked_change_events.append(event_index)
    first_tracked_change_index = min(tracked_change_events, default=None)
    successful_evidence_events: list[int] = []
    bounded_summary_events: list[int] = []
    unbounded_inspect_events: list[int] = []
    manifest_events: list[int] = []
    plan_events: list[int] = []
    failed_commands: dict[str, list[int]] = {}
    successful_commands: dict[str, list[int]] = {}

    for command_index, item in enumerate(command_items):
        command = item.get("command")
        event_index = item.get("event_index")
        if not isinstance(command, str) or not isinstance(event_index, int):
            continue
        succeeded = item.get("status") == "completed" and item.get("exit_code") == 0
        target = successful_commands if succeeded else failed_commands
        target.setdefault(command, []).append(command_index)
        if not succeeded:
            continue
        if _command_kinds(command):
            successful_evidence_events.append(event_index)
        for segment in _expanded_command_segments(command):
            arguments = _rtl_ass_arguments(segment)
            if arguments is None:
                continue
            if arguments[:1] == ["inspect"]:
                if "--summary" in arguments[1:]:
                    bounded_summary_events.append(event_index)
                else:
                    unbounded_inspect_events.append(event_index)
            elif arguments[:2] == ["manifest", "validate"]:
                manifest_events.append(event_index)
            elif arguments[:2] == ["verify", "plan"]:
                plan_events.append(event_index)

    recovered_exact_retries = [
        {
            "command": command,
            "failed_command_indexes": indexes,
            "successful_command_indexes": successful_commands[command],
        }
        for command, indexes in sorted(failed_commands.items())
        if command in successful_commands and max(successful_commands[command]) > min(indexes)
    ]

    def before_tracked_change(events: Sequence[int]) -> bool:
        return first_tracked_change_index is not None and any(index < first_tracked_change_index for index in events)

    return {
        "policy_version": "1.0",
        "first_file_change_event_index": first_change_index,
        "first_tracked_file_change_event_index": first_tracked_change_index,
        "first_successful_evidence_event_index": min(successful_evidence_events, default=None),
        "bounded_project_summary": bool(bounded_summary_events),
        "bounded_project_summary_before_first_tracked_change": before_tracked_change(bounded_summary_events),
        "unbounded_project_inspection": bool(unbounded_inspect_events),
        "unbounded_project_inspection_before_first_tracked_change": before_tracked_change(unbounded_inspect_events),
        "manifest_validated": bool(manifest_events),
        "manifest_validated_before_first_evidence": bool(
            manifest_events and successful_evidence_events and min(manifest_events) < min(successful_evidence_events)
        ),
        "verification_plan_validated": bool(plan_events),
        "baseline_evidence_before_first_tracked_change": before_tracked_change(successful_evidence_events),
        "failed_command_count": sum(len(indexes) for indexes in failed_commands.values()),
        "recovered_exact_retry_count": len(recovered_exact_retries),
        "recovered_exact_retries": recovered_exact_retries,
        "boundary": (
            "derived only from sanitized command completion and file-change ordering; it does not retain or infer "
            "chain-of-thought, command intent, or causality"
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
    normalized = _normalized_command_segment(segment)
    if not normalized:
        return None
    executable = Path(normalized[0]).name
    arguments = normalized[1:]
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


def _is_bare_rtl_ass_invocation(segment: Sequence[str]) -> bool:
    normalized = _normalized_command_segment(segment)
    return bool(normalized) and Path(normalized[0]).name == "rtl-ass"


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
    calibrated_returned: set[str] = set()
    returned_records: dict[str, dict[str, Any]] = {}
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
        result_statuses: list[str] = []
        for item in results:
            record_id = item.get("id") if isinstance(item, dict) else None
            if isinstance(record_id, str):
                result_ids.append(record_id)
            record_status = item.get("status") if isinstance(item, dict) else None
            if isinstance(record_status, str):
                result_statuses.append(record_status)
        filters = receipt.get("filters")
        filter_status = filters.get("status") if isinstance(filters, dict) else None
        calibrated = (
            reason is None
            and bool(results)
            and filter_status in {"verified", "promoted"}
            and len(result_statuses) == len(results)
            and all(status in {"verified", "promoted"} for status in result_statuses)
        )
        if reason is None:
            returned.update(result_ids)
            for item in results:
                returned_records[item["id"]] = {
                    key: item[key]
                    for key in (
                        "id",
                        "content_hash",
                        "role",
                        "status",
                        "source_uri",
                        "source_revision",
                        "source_path",
                        "license_spdx",
                        "namespace",
                    )
                }
        if calibrated:
            calibrated_returned.update(result_ids)
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
                "result_statuses": result_statuses,
                "result_content_hashes": content_hashes,
                "coding_guidance_eligible": calibrated,
            }
        )
    inspected_returned = returned & inspected
    calibrated_inspected = calibrated_returned & inspected
    return {
        "policy_version": "2.2",
        "database_integrity": database_integrity,
        "receipts": receipts,
        "valid_receipt_count": sum(bool(item["strictly_valid"]) for item in receipts),
        "calibrated_receipt_count": sum(bool(item["coding_guidance_eligible"]) for item in receipts),
        "returned_result_ids": sorted(returned),
        "returned_records": [returned_records[key] for key in sorted(returned_records)],
        "content_bound_read_ids": sorted(
            {
                item["id"]
                for item in trace.get("knowledge_reads", [])
                if item["id"] in returned_records
                and item["content_hash"] == returned_records[item["id"]]["content_hash"]
            }
        ),
        "inspected_result_ids": sorted(inspected_returned),
        "calibrated_returned_result_ids": sorted(calibrated_returned),
        "calibrated_inspected_result_ids": sorted(calibrated_inspected),
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
    knowledge_reads: list[dict[str, Any]] = []
    file_changes: list[dict[str, Any]] = []
    file_change_events: list[dict[str, Any]] = []
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
    first_file_change_event_index: int | None = None
    for event_index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
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
                    file_change_events.append(
                        {
                            "path": _redact(change["path"], workspace),
                            "kind": change.get("kind"),
                            "event_index": event_index,
                        }
                    )
                    if first_file_change_event_index is None:
                        first_file_change_event_index = event_index
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
                "event_index": event_index,
            }
        )
        command_succeeded = item.get("status") == "completed" and exit_code == 0
        if command_succeeded:
            # Retain only identities of complete, hash-matching content outputs, not source or reasoning text.
            for segment in _expanded_command_segments(command):
                arguments = _rtl_ass_arguments(segment)
                if arguments is None or len(arguments) < 4 or arguments[:2] != ["kb", "show"]:
                    continue
                if "--include-content" not in arguments[3:]:
                    continue
                try:
                    output = json.loads(item.get("aggregated_output", ""))
                except (ValueError, TypeError):
                    continue
                if (
                    isinstance(output, dict)
                    and output.get("id") == arguments[2]
                    and isinstance(output.get("content"), str)
                    and hashlib.sha256(output["content"].encode("utf-8")).hexdigest() == output.get("content_hash")
                ):
                    knowledge_reads.append(
                        {"id": output["id"], "content_hash": output["content_hash"], "event_index": event_index}
                    )
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
        "knowledge_reads": knowledge_reads,
        "file_changes": file_changes,
        "file_change_events": file_change_events,
        "first_file_change_event_index": first_file_change_event_index,
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
    source_retrieval_database: Path | None,
    retrieval_treatment: Mapping[str, Any] | None,
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
        retrieval_database=source_retrieval_database,
    )
    workspace_retrieval_database = workspace / ".rtl-ass" / "eval.db"
    expected_retrieval_database_hash = (
        hash_file(workspace_retrieval_database)
        if (ablation == "retrieval" or (ablation == "product" and condition == "on"))
        else None
    )
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
    workflow_mechanisms = _workflow_mechanisms(trace, tracked_paths=initial)
    knowledge_retrieval = _workspace_retrieval(
        workspace,
        trace,
        expected_database_hash=expected_retrieval_database_hash,
    )
    knowledge_application = audit_application(workspace, knowledge_retrieval, grade, retrieval_treatment)
    workflow_audit = _workflow_audit(
        trace,
        case,
        condition,
        grade,
        ablation=ablation,
        workflow_mechanisms=workflow_mechanisms,
        knowledge_retrieval=knowledge_retrieval,
        retrieval_treatment=retrieval_treatment,
        knowledge_application=knowledge_application,
    )
    workflow_efficiency = _workflow_efficiency(trace, agent_evidence)
    result = {
        "schema_version": "1.0",
        "run_id": run_id,
        "case": case.identifier,
        "replicate": replicate,
        "condition": condition,
        "ablation": ablation,
        "retrieval_treatment": retrieval_treatment["treatment"] if retrieval_treatment is not None else None,
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
        "workflow_mechanisms": workflow_mechanisms,
        "knowledge_retrieval": knowledge_retrieval,
        "knowledge_application": knowledge_application,
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
        mechanisms = [item.get("workflow_mechanisms", {}) for item in valid_items]
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
            "rtl_ass_eda_adapter_commands": sum(
                len(item.get("workflow_audit", {}).get("rtl_ass_eda_adapter_commands", [])) for item in valid_items
            ),
            "workflow_efficient_runs": workflow_efficient,
            "workflow_efficiency_finding_runs": valid - workflow_efficient,
            "redundant_evidence_executions": sum(
                int(item.get("workflow_efficiency", {}).get("redundant_evidence_execution_count", 0))
                for item in valid_items
            ),
            "post_ready_eda_commands": sum(
                len(item.get("workflow_efficiency", {}).get("post_ready_eda_commands", [])) for item in valid_items
            ),
            "failed_rtl_ass_entrypoint_commands": sum(
                len(item.get("workflow_efficiency", {}).get("failed_rtl_ass_entrypoint_commands", []))
                for item in valid_items
            ),
            "runs_with_bounded_project_summary": sum(
                bool(mechanism.get("bounded_project_summary")) for mechanism in mechanisms
            ),
            "runs_with_unbounded_project_inspection": sum(
                bool(mechanism.get("unbounded_project_inspection")) for mechanism in mechanisms
            ),
            "runs_with_baseline_evidence_before_first_tracked_change": sum(
                bool(mechanism.get("baseline_evidence_before_first_tracked_change")) for mechanism in mechanisms
            ),
            "runs_with_manifest_validation": sum(bool(mechanism.get("manifest_validated")) for mechanism in mechanisms),
            "failed_commands": sum(int(mechanism.get("failed_command_count", 0)) for mechanism in mechanisms),
            "recovered_exact_retries": sum(
                int(mechanism.get("recovered_exact_retry_count", 0)) for mechanism in mechanisms
            ),
            "valid_retrieval_receipts": sum(int(retrieval.get("valid_receipt_count", 0)) for retrieval in retrievals),
            "calibrated_retrieval_receipts": sum(
                int(retrieval.get("calibrated_receipt_count", 0)) for retrieval in retrievals
            ),
            "runs_with_valid_retrieval": sum(
                int(retrieval.get("valid_receipt_count", 0)) > 0 for retrieval in retrievals
            ),
            "retrieval_results_returned": sum(
                len(retrieval.get("returned_result_ids", [])) for retrieval in retrievals
            ),
            "retrieval_results_inspected": sum(
                len(retrieval.get("inspected_result_ids", [])) for retrieval in retrievals
            ),
            "calibrated_retrieval_results_inspected": sum(
                len(retrieval.get("calibrated_inspected_result_ids", [])) for retrieval in retrievals
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
        choices=("skill", "retrieval", "product"),
        default="skill",
        help=(
            "skill: native versus Skill without knowledge; retrieval: Skill with empty versus populated knowledge; "
            "product: native versus Skill with relevant calibrated knowledge"
        ),
    )
    parser.add_argument(
        "--retrieval-database",
        type=Path,
        help="audited database with 1-3 calibrated cards copied only to the treated on condition",
    )
    parser.add_argument(
        "--retrieval-treatment-manifest",
        type=Path,
        help="human-reviewed relevant or plausible-irrelevant judgment bound to the exact case and card hashes",
    )
    case_selection = parser.add_mutually_exclusive_group()
    case_selection.add_argument("--case", choices=sorted(CASES), default=None)
    case_selection.add_argument(
        "--soc-case",
        choices=sorted(SOC_CASES),
        help="materialize a pinned repository-scale case from --source-repository",
    )
    parser.add_argument(
        "--source-repository",
        type=Path,
        help="local Git object store used only to materialize the selected pinned SoC case",
    )
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
    retrieval_database = args.retrieval_database.resolve() if args.retrieval_database is not None else None
    retrieval_treatment_path = (
        args.retrieval_treatment_manifest.resolve() if args.retrieval_treatment_manifest is not None else None
    )
    if (args.ablation in KNOWLEDGE_TREATMENT_ABLATIONS) != (
        retrieval_database is not None and retrieval_treatment_path is not None
    ):
        raise SystemExit(
            "--ablation retrieval/product requires --retrieval-database and --retrieval-treatment-manifest; "
            "both are forbidden for the skill-only ablation"
        )
    if retrieval_database is not None and (not retrieval_database.is_file() or retrieval_database.is_symlink()):
        raise SystemExit("retrieval database must be a regular non-symlink file")
    if args.outer_bwrap and args.sandbox_network:
        raise SystemExit("--sandbox-network only configures Codex's inner workspace-write sandbox")
    if args.outer_bwrap and args.parallel != 1:
        raise SystemExit("resource-supervised --outer-bwrap requires --parallel 1")
    if (args.soc_case is None) != (args.source_repository is None):
        raise SystemExit("--soc-case and --source-repository must be supplied together")
    resource_preflight = _resource_preflight(DEFAULT_RESOURCE_POLICY) if args.outer_bwrap else None
    codex_version = _codex_version(args.codex)
    source_snapshot: dict[str, Any] | None = None
    if args.soc_case is not None and args.source_repository is not None:
        case, source_snapshot = materialize_soc_case(
            args.soc_case,
            args.source_repository,
            output / "case-source",
        )
    else:
        case = get_case(args.case or DEFAULT_CASE_ID)
    retrieval_contamination_audit = (
        _validate_retrieval_ablation_database(retrieval_database, case) if retrieval_database is not None else None
    )
    retrieval_treatment = (
        _load_retrieval_treatment(
            retrieval_treatment_path,
            case=case,
            database_audit=retrieval_contamination_audit,
        )
        if retrieval_treatment_path is not None and retrieval_contamination_audit is not None
        else None
    )
    if (
        args.ablation == "product"
        and retrieval_treatment is not None
        and retrieval_treatment["treatment"] != "relevant"
    ):
        raise SystemExit("--ablation product requires a relevant treatment manifest")
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
            "source_retrieval_database": retrieval_database,
            "retrieval_treatment": retrieval_treatment,
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
    harness_paths = [
        Path(__file__).resolve(),
        ROOT / "evals" / "retrieval_treatment.py",
        ROOT / "evals" / "knowledge_application.py",
        ROOT / "evals" / "file_application_case.py",
        ROOT / "evals" / "workflow_cases.py",
    ]
    if source_snapshot is not None:
        harness_paths.append(ROOT / "evals" / "soc_workflow_cases.py")
    report = {
        "schema_version": "1.0",
        "kind": "codex-skill-workflow-audit",
        "generated_at": datetime.now(UTC).isoformat(),
        "case": case.identifier,
        "ablation": args.ablation,
        "retrieval_database_hash": hash_file(retrieval_database) if retrieval_database is not None else None,
        "retrieval_contamination_audit": retrieval_contamination_audit,
        "retrieval_treatment": retrieval_treatment,
        "retrieval_treatment_manifest_hash": (
            hash_file(retrieval_treatment_path) if retrieval_treatment_path is not None else None
        ),
        "source_snapshot": source_snapshot,
        "prompt_hash": hashlib.sha256(case.prompt.encode()).hexdigest(),
        "fixture_hash": _hash_tree(case.public_fixture),
        "hidden_grader_hash": _hash_tree(case.public_fixture.parent / "private"),
        "harness_hash": _hash_files(harness_paths),
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
        "skill_required_mechanisms": sorted(case.skill_required_mechanisms),
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
