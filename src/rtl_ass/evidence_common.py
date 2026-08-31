"""Shared identities and artifact contracts for open-tool evidence adapters."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

from rtl_ass.errors import RtlAssError
from rtl_ass.integrity import hash_file, hash_json
from rtl_ass.project import RTL_SUFFIXES

_VERILOG_IDENTIFIER = re.compile(r"^[A-Za-z_]\w*$")


class EvidenceBundle(Protocol):
    @property
    def top(self) -> str: ...

    @property
    def input_hash(self) -> str: ...

    @property
    def subject_hashes(self) -> list[dict[str, Any]]: ...

    def inputs_unchanged(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class SourceBundle:
    sources: tuple[Path, ...]
    display_paths: tuple[str, ...]
    content_hashes: tuple[str, ...]
    top: str

    @classmethod
    def create(cls, sources: Sequence[str | Path], top: str) -> "SourceBundle":
        validate_verilog_identifier(top, "top")
        display_paths = tuple(Path(source).as_posix() for source in sources)
        resolved = tuple(Path(source).resolve() for source in sources)
        if not resolved:
            raise RtlAssError("sources_required", "at least one RTL source is required")
        if len(set(resolved)) != len(resolved):
            raise RtlAssError("duplicate_source", "source list contains duplicate paths")
        invalid = [
            str(source) for source in resolved if not source.is_file() or source.suffix.lower() not in RTL_SUFFIXES
        ]
        if invalid:
            raise RtlAssError(
                "invalid_source", "all sources must be existing Verilog/SystemVerilog files", {"paths": invalid}
            )
        content_hashes = tuple(hash_file(source) for source in resolved)
        return cls(sources=resolved, display_paths=display_paths, content_hashes=content_hashes, top=top)

    @property
    def source_hashes(self) -> list[dict[str, Any]]:
        return [
            {"index": index, "path": display_path, "content_hash": content_hash}
            for index, (display_path, content_hash) in enumerate(
                zip(self.display_paths, self.content_hashes, strict=True)
            )
        ]

    @property
    def subject_hashes(self) -> list[dict[str, Any]]:
        return self.source_hashes

    @property
    def input_hash(self) -> str:
        identities = [{"index": item["index"], "content_hash": item["content_hash"]} for item in self.source_hashes]
        return hash_json({"top": self.top, "sources": identities})

    def inputs_unchanged(self) -> bool:
        return all(
            source.is_file() and hash_file(source) == expected
            for source, expected in zip(self.sources, self.content_hashes, strict=True)
        )


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
class FormalInputBundle:
    source_bundle: SourceBundle
    depth: int
    initialization: str

    @classmethod
    def create(
        cls,
        sources: Sequence[str | Path],
        *,
        top: str,
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
        return cls(SourceBundle.create(sources, top), depth, initialization)

    @property
    def sources(self) -> tuple[Path, ...]:
        return self.source_bundle.sources

    @property
    def top(self) -> str:
        return self.source_bundle.top

    @property
    def subject_hashes(self) -> list[dict[str, Any]]:
        return self.source_bundle.subject_hashes

    @property
    def input_hash(self) -> str:
        identities = [{"index": item["index"], "content_hash": item["content_hash"]} for item in self.subject_hashes]
        return hash_json(
            {
                "top": self.top,
                "subjects": identities,
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

    @classmethod
    def create(
        cls,
        reference_sources: Sequence[str | Path],
        implementation_sources: Sequence[str | Path],
        *,
        reference_top: str,
        implementation_top: str,
        depth: int,
        input_domain: str = "defined",
    ) -> "EquivalenceInputBundle":
        validate_depth(depth)
        if input_domain not in {"defined", "undefined"}:
            raise RtlAssError(
                "invalid_equivalence_input_domain",
                "equivalence input domain must be defined or undefined",
                {"input_domain": input_domain},
            )
        reference = SourceBundle.create(reference_sources, reference_top)
        implementation = SourceBundle.create(implementation_sources, implementation_top)
        if reference.input_hash == implementation.input_hash:
            raise RtlAssError(
                "identical_equivalence_inputs",
                "equivalence requires distinct reference and implementation identities",
            )
        return cls(reference, implementation, depth, input_domain)

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
        identities: list[dict[str, Any]] = []
        for role, bundle in (("reference", self.reference), ("implementation", self.implementation)):
            for item in bundle.subject_hashes:
                identities.append(
                    {
                        "index": len(identities),
                        "role": role,
                        "content_hash": item["content_hash"],
                    }
                )
        return hash_json(
            {
                "reference_top": self.reference.top,
                "implementation_top": self.implementation.top,
                "depth": self.depth,
                "input_domain": self.input_domain,
                "subjects": identities,
            }
        )

    def inputs_unchanged(self) -> bool:
        return self.reference.inputs_unchanged() and self.implementation.inputs_unchanged()


def validate_verilog_identifier(value: str, field: str) -> None:
    if not isinstance(value, str) or not _VERILOG_IDENTIFIER.fullmatch(value):
        raise RtlAssError("invalid_top", f"{field} must be a Verilog identifier", {"field": field, "value": value})


def tool_version(executable: str, arguments: list[str]) -> str:
    try:
        result = subprocess.run(
            [executable, *arguments],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RtlAssError(
            "tool_version_failed",
            "the discovered RTL tool did not provide a bounded version response",
            {"tool": executable, "reason": str(exc)},
        ) from exc
    return result.stdout.strip().splitlines()[0] if result.stdout.strip() else "unknown"


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
    tool_version_value: str,
    bundle: EvidenceBundle,
    commands: list[list[str]],
    artifacts: list[str],
    started_at: str,
    finished_at: str,
    summary: dict[str, Any],
) -> dict[str, Any]:
    artifact_hashes = [
        {"index": index, "path": path, "content_hash": hash_file(path)} for index, path in enumerate(artifacts)
    ]
    return {
        "schema_version": "1.0",
        "kind": kind,
        "status": status,
        "tool": {"name": tool_name, "version": tool_version_value},
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
