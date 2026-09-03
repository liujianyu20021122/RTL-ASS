"""Shared identities and artifact contracts for open-tool evidence adapters."""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, Sequence

from rtl_ass.compile_manifest import CompileInput, CompileManifest, coerce_compile_manifest, validate_compile_identifier
from rtl_ass.errors import RtlAssError
from rtl_ass.integrity import hash_file, hash_json


class EvidenceBundle(Protocol):
    @property
    def top(self) -> str: ...

    @property
    def input_hash(self) -> str: ...

    @property
    def subject_hashes(self) -> list[dict[str, Any]]: ...

    def inputs_unchanged(self) -> bool: ...


SourceBundle = CompileManifest


@dataclass(frozen=True, slots=True)
class StaInputBundle:
    files: tuple[Path, ...]
    display_paths: tuple[str, ...]
    content_hashes: tuple[str, ...]
    roles: tuple[str, ...]
    top: str

    @classmethod
    def create(
        cls,
        *,
        netlist: str | Path,
        liberty: str | Path,
        constraints: str | Path,
        top: str,
    ) -> "StaInputBundle":
        validate_verilog_identifier(top, "top")
        provided = (Path(netlist), Path(liberty), Path(constraints))
        resolved = tuple(path.resolve() for path in provided)
        roles = ("netlist", "liberty", "constraints")
        expected_suffixes = ({".v", ".sv"}, {".lib"}, {".sdc"})
        invalid = [
            {"role": role, "path": str(path)}
            for role, path, suffixes in zip(roles, resolved, expected_suffixes, strict=True)
            if not path.is_file() or path.suffix.lower() not in suffixes
        ]
        if invalid:
            raise RtlAssError(
                "invalid_sta_input",
                "STA requires an existing Verilog netlist, Liberty file, and SDC file",
                {"invalid": invalid},
            )
        if len(set(resolved)) != len(resolved):
            raise RtlAssError("duplicate_sta_input", "STA inputs must be distinct files")
        hashes = tuple(hash_file(path) for path in resolved)
        return cls(
            files=resolved,
            display_paths=tuple(path.as_posix() for path in provided),
            content_hashes=hashes,
            roles=roles,
            top=top,
        )

    @property
    def subject_hashes(self) -> list[dict[str, Any]]:
        return [
            {"index": index, "path": path, "content_hash": content_hash}
            for index, (path, content_hash) in enumerate(zip(self.display_paths, self.content_hashes, strict=True))
        ]

    @property
    def input_hash(self) -> str:
        inputs = [
            {"index": index, "role": role, "content_hash": content_hash}
            for index, (role, content_hash) in enumerate(zip(self.roles, self.content_hashes, strict=True))
        ]
        return hash_json({"top": self.top, "inputs": inputs})

    def inputs_unchanged(self) -> bool:
        return all(
            path.is_file() and hash_file(path) == expected
            for path, expected in zip(self.files, self.content_hashes, strict=True)
        )


@dataclass(frozen=True, slots=True)
class SynthesisInputBundle:
    source_bundle: SourceBundle
    liberty: Path | None
    liberty_display_path: str | None
    liberty_content_hash: str | None

    @classmethod
    def create(
        cls,
        sources: CompileInput,
        *,
        top: str | None,
        liberty: str | Path | None,
    ) -> "SynthesisInputBundle":
        source_bundle = coerce_compile_manifest(sources, top)
        if liberty is None:
            return cls(source_bundle, None, None, None)
        provided = Path(liberty)
        resolved = provided.resolve()
        if provided.is_symlink() or not resolved.is_file() or resolved.suffix.lower() != ".lib":
            raise RtlAssError(
                "invalid_synthesis_liberty",
                "mapped synthesis requires an existing non-symlink Liberty file",
                {"path": provided.as_posix()},
            )
        return cls(source_bundle, resolved, provided.as_posix(), hash_file(resolved))

    @property
    def top(self) -> str:
        return self.source_bundle.top

    @property
    def subject_hashes(self) -> list[dict[str, Any]]:
        subjects = list(self.source_bundle.subject_hashes)
        if self.liberty_display_path is not None and self.liberty_content_hash is not None:
            subjects.append(
                {
                    "index": len(subjects),
                    "path": self.liberty_display_path,
                    "content_hash": self.liberty_content_hash,
                }
            )
        return subjects

    @property
    def input_hash(self) -> str:
        return hash_json(
            {
                "compile_input_hash": self.source_bundle.input_hash,
                "mode": "liberty-mapped" if self.liberty is not None else "generic-structural",
                "liberty_content_hash": self.liberty_content_hash,
            }
        )

    def inputs_unchanged(self) -> bool:
        return self.source_bundle.inputs_unchanged() and (
            self.liberty is None
            or (
                self.liberty.is_file()
                and not self.liberty.is_symlink()
                and hash_file(self.liberty) == self.liberty_content_hash
            )
        )

    def option_summary(self) -> dict[str, Any]:
        return {
            **self.source_bundle.option_summary(),
            "synthesis_mode": "liberty-mapped" if self.liberty is not None else "generic-structural",
            "liberty_file_count": int(self.liberty is not None),
        }


@dataclass(frozen=True, slots=True)
class ToolVersionProbe:
    """A bounded version probe whose diagnostic cannot masquerade as a version."""

    version: str
    status: Literal["pass", "failed", "timeout", "launch_failed", "empty_response"]
    command: tuple[str, ...]
    returncode: int | None = None
    diagnostic: str | None = None

    def summary(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "command": list(self.command),
        }
        if self.returncode is not None:
            result["returncode"] = self.returncode
        if self.diagnostic is not None:
            result["diagnostic"] = self.diagnostic
        return result


@dataclass(frozen=True, slots=True)
class ToolExecution:
    """Normalized result of one bounded external-tool process."""

    outcome: Literal["completed", "timeout", "launch_failed"]
    returncode: int | None
    stdout: str
    stderr: str
    error_type: str | None = None

    def completed_returncode(self) -> int:
        if self.outcome != "completed" or self.returncode is None:
            raise RtlAssError(
                "invalid_tool_execution",
                "a non-completed tool execution has no return code",
                {"outcome": self.outcome},
            )
        return self.returncode


@dataclass(frozen=True, slots=True)
class FormalInputBundle:
    source_bundle: SourceBundle
    depth: int
    initialization: str

    @classmethod
    def create(
        cls,
        sources: CompileInput,
        *,
        top: str | None,
        depth: int,
        initialization: str,
    ) -> "FormalInputBundle":
        validate_depth(depth)
        if initialization not in {"defined", "zero"}:
            raise RtlAssError(
                "invalid_formal_initialization",
                "formal initialization must be defined or zero",
                {"initialization": initialization},
            )
        return cls(coerce_compile_manifest(sources, top), depth, initialization)

    @property
    def sources(self) -> tuple[Path, ...]:
        return self.source_bundle.compilation_units

    @property
    def top(self) -> str:
        return self.source_bundle.top

    @property
    def subject_hashes(self) -> list[dict[str, Any]]:
        return self.source_bundle.subject_hashes

    @property
    def input_hash(self) -> str:
        return hash_json(
            {
                "compile_input_hash": self.source_bundle.input_hash,
                "depth": self.depth,
                "initialization": self.initialization,
            }
        )

    def inputs_unchanged(self) -> bool:
        return self.source_bundle.inputs_unchanged()


@dataclass(frozen=True, slots=True)
class EquivalenceInputBundle:
    reference: SourceBundle
    implementation: SourceBundle
    depth: int
    input_domain: str
    initialization: str

    @classmethod
    def create(
        cls,
        reference_sources: CompileInput,
        implementation_sources: CompileInput,
        *,
        reference_top: str | None,
        implementation_top: str | None,
        depth: int,
        input_domain: str = "defined",
        initialization: str = "none",
    ) -> "EquivalenceInputBundle":
        validate_depth(depth)
        if input_domain not in {"defined", "undefined"}:
            raise RtlAssError(
                "invalid_equivalence_input_domain",
                "equivalence input domain must be defined or undefined",
                {"input_domain": input_domain},
            )
        allowed_initializations = {"none"} if depth == 1 else {"zero"}
        if initialization not in allowed_initializations:
            raise RtlAssError(
                "invalid_equivalence_initialization",
                (
                    "combinational equivalence requires initialization=none"
                    if depth == 1
                    else "sequential equivalence requires the explicit zero-default initialization policy"
                ),
                {"depth": depth, "initialization": initialization},
            )
        reference = coerce_compile_manifest(reference_sources, reference_top)
        implementation = coerce_compile_manifest(implementation_sources, implementation_top)
        if reference.input_hash == implementation.input_hash:
            raise RtlAssError(
                "identical_equivalence_inputs",
                "equivalence requires distinct reference and implementation identities",
            )
        return cls(reference, implementation, depth, input_domain, initialization)

    @property
    def top(self) -> str:
        return self.implementation.top

    @property
    def subject_hashes(self) -> list[dict[str, Any]]:
        subjects: list[dict[str, Any]] = []
        for bundle in (self.reference, self.implementation):
            for item in bundle.subject_hashes:
                subjects.append(
                    {
                        "index": len(subjects),
                        "path": item["path"],
                        "content_hash": item["content_hash"],
                    }
                )
        return subjects

    @property
    def input_hash(self) -> str:
        return hash_json(
            {
                "reference_compile_input_hash": self.reference.input_hash,
                "implementation_compile_input_hash": self.implementation.input_hash,
                "depth": self.depth,
                "input_domain": self.input_domain,
                "initialization": self.initialization,
            }
        )

    def inputs_unchanged(self) -> bool:
        return self.reference.inputs_unchanged() and self.implementation.inputs_unchanged()


def validate_verilog_identifier(value: str, field: str) -> None:
    try:
        validate_compile_identifier(value, field)
    except RtlAssError as exc:
        raise RtlAssError(
            "invalid_top", f"{field} must be a Verilog identifier", {"field": field, "value": value}
        ) from exc


def tool_version(executable: str, arguments: list[str]) -> ToolVersionProbe:
    command = (executable, *arguments)
    result = run_tool_command(command, timeout_seconds=10, merge_stderr=True)
    if result.outcome == "timeout":
        return ToolVersionProbe(
            version="unknown",
            status="timeout",
            command=command,
            diagnostic=_bounded_diagnostic(result.stdout),
        )
    if result.outcome == "launch_failed":
        return ToolVersionProbe(
            version="unknown",
            status="launch_failed",
            command=command,
            diagnostic=_bounded_diagnostic(result.stderr),
        )
    diagnostic = _bounded_diagnostic(result.stdout)
    returncode = result.completed_returncode()
    if returncode != 0:
        return ToolVersionProbe(
            version="unknown",
            status="failed",
            command=command,
            returncode=returncode,
            diagnostic=diagnostic,
        )
    if diagnostic is None:
        return ToolVersionProbe(
            version="unknown",
            status="empty_response",
            command=command,
            returncode=returncode,
        )
    return ToolVersionProbe(
        version=diagnostic,
        status="pass",
        command=command,
        returncode=returncode,
    )


def run_tool_command(
    command: Sequence[str],
    *,
    timeout_seconds: int,
    cwd: str | Path | None = None,
    merge_stderr: bool = False,
) -> ToolExecution:
    """Execute one discovered tool and preserve timeout/launch/exit attribution."""

    try:
        result = subprocess.run(
            command,
            check=False,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return ToolExecution(
            outcome="timeout",
            returncode=None,
            stdout=timeout_text(exc.stdout),
            stderr="" if merge_stderr else timeout_text(exc.stderr),
        )
    except OSError as exc:
        return ToolExecution(
            outcome="launch_failed",
            returncode=None,
            stdout="",
            stderr=str(exc),
            error_type=type(exc).__name__,
        )
    return ToolExecution(
        outcome="completed",
        returncode=result.returncode,
        stdout=result.stdout,
        stderr="" if merge_stderr else result.stderr,
    )


def _bounded_diagnostic(value: str | bytes | None) -> str | None:
    text = timeout_text(value).strip()
    if not text:
        return None
    return text.splitlines()[0][:512]


def run_directory(root: str | Path, kind: str, tool: str) -> Path:
    artifact_root = Path(root)
    artifact_root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{kind}-{tool}-", dir=artifact_root))


def write_evidence(run_directory_path: Path, evidence: dict[str, Any]) -> dict[str, Any]:
    destination = run_directory_path / "run-evidence.json"
    temporary = run_directory_path / ".run-evidence.json.tmp"
    evidence["evidence_file"] = destination.as_posix()
    temporary.write_text(json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
    return evidence


def base_evidence(
    *,
    kind: str,
    status: str,
    tool_name: str,
    tool_version_value: str | ToolVersionProbe,
    bundle: EvidenceBundle,
    commands: list[list[str]],
    artifacts: list[str],
    started_at: str,
    finished_at: str,
    summary: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(tool_version_value, ToolVersionProbe):
        version = tool_version_value.version
        summary = {**summary, "tool_version_probe": tool_version_value.summary()}
    else:
        version = tool_version_value
    artifact_hashes = [
        {"index": index, "path": path, "content_hash": hash_file(path)} for index, path in enumerate(artifacts)
    ]
    return {
        "schema_version": "1.0",
        "kind": kind,
        "status": status,
        "tool": {"name": tool_name, "version": version},
        "input_hash": bundle.input_hash,
        "subject_hashes": bundle.subject_hashes,
        "top": bundle.top,
        "commands": commands,
        "artifacts": artifacts,
        "artifact_hashes": artifact_hashes,
        "started_at": started_at,
        "finished_at": finished_at,
        "summary": summary,
        "claim_scope": "tool execution evidence only",
    }


def unavailable_evidence(
    *,
    kind: str,
    tool_name: str,
    bundle: EvidenceBundle,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "kind": kind,
        "status": "not_available",
        "tool": {"name": tool_name, "version": "not_available"},
        "input_hash": bundle.input_hash,
        "subject_hashes": bundle.subject_hashes,
        "top": bundle.top,
        "commands": [],
        "artifacts": [],
        "artifact_hashes": [],
        "summary": dict(summary or {}),
        "claim_scope": "tool discovery only",
    }


def input_stable_status(
    bundle: EvidenceBundle,
    status: str,
    summary: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    if bundle.inputs_unchanged():
        return status, summary
    return "blocked", {**summary, "input_changed_during_run": True}


def validate_timeout(timeout_seconds: int) -> None:
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or timeout_seconds < 1
        or timeout_seconds > 3600
    ):
        raise RtlAssError(
            "invalid_timeout",
            "timeout must be an integer between 1 and 3600 seconds",
            {"timeout_seconds": timeout_seconds},
        )


def validate_depth(depth: int) -> None:
    if isinstance(depth, bool) or not isinstance(depth, int) or depth < 1 or depth > 1000:
        raise RtlAssError(
            "invalid_formal_depth", "formal depth must be an integer between 1 and 1000", {"depth": depth}
        )


def timeout_text(value: str | bytes | None) -> str:
    """Normalize TimeoutExpired output without duplicating adapter-specific fallbacks."""
    if isinstance(value, str):
        return value
    return (value or b"").decode(errors="replace")


def yosys_quote(path: Path) -> str:
    value = str(path)
    if "\n" in value or "\r" in value:
        raise RtlAssError("invalid_source_path", "Yosys source paths must not contain line breaks")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
