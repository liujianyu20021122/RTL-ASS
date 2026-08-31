"""Safe, non-executing RTL project inspection."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from rtl_ass.errors import RtlAssError
from rtl_ass.kb.models import RecordRole

RTL_SUFFIXES = frozenset({".v", ".vh", ".sv", ".svh"})
IGNORED_DIRECTORIES = frozenset(
    {".git", ".hg", ".svn", ".rtl-ass", "__pycache__", "build", "dist", "node_modules", "research"}
)

_MODULE = re.compile(r"(?m)^\s*module\s+(?:automatic\s+)?([A-Za-z_]\w*)")
_INTERFACE = re.compile(r"(?m)^\s*interface\s+([A-Za-z_]\w*)")
_PACKAGE = re.compile(r"(?m)^\s*package\s+([A-Za-z_]\w*)")
_INCLUDE = re.compile(r"`include\s+\"([^\"]+)\"")
_IDENTIFIER_TOKEN = re.compile(r"\b[A-Za-z_]\w*\b")
_TB_NAME = re.compile(r"(?:^|[_-])(tb|testbench|test)(?:[_-]|$)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class RoleClassification:
    role: RecordRole
    confidence: str
    basis: tuple[str, ...]


def strip_comments(text: str) -> str:
    """Remove comments while preserving strings, newlines, and character offsets."""
    output: list[str] = []
    index = 0
    state = "normal"
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if state == "normal":
            if char == "/" and next_char == "/":
                output.extend((" ", " "))
                index += 2
                state = "line-comment"
                continue
            if char == "/" and next_char == "*":
                output.extend((" ", " "))
                index += 2
                state = "block-comment"
                continue
            output.append(char)
            if char == '"':
                state = "string"
            index += 1
            continue
        if state == "string":
            output.append(char)
            if char == "\\" and next_char:
                output.append(next_char)
                index += 2
                continue
            if char == '"':
                state = "normal"
            index += 1
            continue
        if state == "line-comment":
            output.append("\n" if char == "\n" else " ")
            if char == "\n":
                state = "normal"
            index += 1
            continue
        output.append("\n" if char == "\n" else " ")
        if char == "*" and next_char == "/":
            output.append(" ")
            index += 2
            state = "normal"
        else:
            index += 1
    return "".join(output)


def classify_role(path: Path, source_without_comments: str) -> RoleClassification:
    stem = path.stem.lower()
    basis: list[str] = []
    if _TB_NAME.search(stem):
        basis.append("filename-test-pattern")
    if re.search(r"\b(initial|final)\b", source_without_comments) and re.search(
        r"\$(finish|fatal|error|display|monitor)\b", source_without_comments
    ):
        basis.append("simulation-control-constructs")
    if basis:
        return RoleClassification(RecordRole.TESTBENCH, "high" if len(basis) > 1 else "medium", tuple(basis))
    if re.search(r"\b(assert|assume|cover)\s+property\b|\bproperty\s+[A-Za-z_]", source_without_comments):
        return RoleClassification(RecordRole.ASSERTION, "medium", ("property-constructs",))
    if _INTERFACE.search(source_without_comments) and not _MODULE.search(source_without_comments):
        return RoleClassification(RecordRole.INTERFACE, "high", ("interface-declaration",))
    if _PACKAGE.search(source_without_comments) and not _MODULE.search(source_without_comments):
        return RoleClassification(RecordRole.PACKAGE, "high", ("package-declaration",))
    return RoleClassification(RecordRole.RTL_DESIGN, "medium", ("default-rtl-source",))


def identifier_hints(source_without_comments: str, keywords: tuple[str, ...]) -> list[str]:
    identifiers = set(_IDENTIFIER_TOKEN.findall(source_without_comments))
    return sorted(
        identifier for identifier in identifiers if any(keyword in identifier.lower() for keyword in keywords)
    )[:32]


def analyze_source(path: Path, text: str, relative_path: str) -> dict[str, Any]:
    clean = strip_comments(text)
    classification = classify_role(path, clean)
    return {
        "path": relative_path,
        "language": "systemverilog" if path.suffix.lower() in {".sv", ".svh"} else "verilog",
        "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "byte_count": len(text.encode("utf-8")),
        "role": classification.role.value,
        "role_confidence": classification.confidence,
        "role_basis": list(classification.basis),
        "modules": sorted(set(_MODULE.findall(clean))),
        "interfaces": sorted(set(_INTERFACE.findall(clean))),
        "packages": sorted(set(_PACKAGE.findall(clean))),
        "includes": sorted(set(_INCLUDE.findall(clean))),
        "clock_hints": identifier_hints(clean, ("clk", "clock")),
        "reset_hints": identifier_hints(clean, ("rst", "reset")),
    }


def discover_sources(root: Path, *, follow_symlinks: bool = False) -> Iterable[Path]:
    if root.is_file():
        if root.suffix.lower() not in RTL_SUFFIXES:
            raise RtlAssError("unsupported_source", "source file must be Verilog or SystemVerilog", {"path": str(root)})
        yield root
        return
    if not root.is_dir():
        raise RtlAssError("project_not_found", "RTL project path does not exist", {"path": str(root)})

    for current, directories, filenames in os.walk(root, followlinks=follow_symlinks):
        directories[:] = sorted(
            directory
            for directory in directories
            if directory not in IGNORED_DIRECTORIES
            and (follow_symlinks or not (Path(current) / directory).is_symlink())
        )
        for filename in sorted(filenames):
            path = Path(current) / filename
            if path.suffix.lower() in RTL_SUFFIXES and (follow_symlinks or not path.is_symlink()):
                yield path


def inspect_project(
    project_path: str | Path,
    *,
    max_source_bytes: int = 5 * 1024 * 1024,
    follow_symlinks: bool = False,
) -> dict[str, Any]:
    if max_source_bytes < 1:
        raise RtlAssError("invalid_size_limit", "max_source_bytes must be positive")
    root = Path(project_path)
    resolved_root = root.resolve()
    base = resolved_root.parent if resolved_root.is_file() else resolved_root
    files: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for source_path in discover_sources(resolved_root, follow_symlinks=follow_symlinks):
        relative = source_path.relative_to(base).as_posix()
        size = source_path.stat().st_size
        if size > max_source_bytes:
            skipped.append({"path": relative, "reason": "source_too_large", "byte_count": size})
            continue
        try:
            text = source_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            skipped.append({"path": relative, "reason": "not_utf8", "offset": exc.start})
            continue
        files.append(analyze_source(source_path, text, relative))

    role_counts: dict[str, int] = {}
    for item in files:
        role_counts[item["role"]] = role_counts.get(item["role"], 0) + 1
    return {
        "schema_version": "1.0",
        "project": root.as_posix(),
        "file_count": len(files),
        "role_counts": dict(sorted(role_counts.items())),
        "files": files,
        "skipped": skipped,
        "limitations": [
            "role, clock, and reset fields are lexical hints rather than elaborated semantic proof",
            "inspection does not execute or elaborate source files",
        ],
    }
