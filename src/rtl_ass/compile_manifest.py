"""Audited compile inputs shared by every source-based tool adapter."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence, TypeAlias, Union

from rtl_ass.errors import RtlAssError
from rtl_ass.integrity import hash_file, hash_json, parse_json, read_utf8_exact
from rtl_ass.project import RTL_SUFFIXES

COMPILE_MANIFEST_SCHEMA_VERSION = "1.0"
MAX_COMPILE_FILES = 4096
MAX_COMPILE_OPTIONS = 4096
MAX_INCLUDE_DIRS = 256
MAX_INCLUDE_FILES = 4096
MAX_INCLUDE_BYTES = 256 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_VALUE = re.compile(r"^[A-Za-z0-9_.$'+*/%<>=!&|^~?:,()\-]+$")
_LANGUAGES = frozenset({"systemverilog", "verilog-2005"})
_MANIFEST_KEYS = frozenset(
    {"schema_version", "top", "language", "sources", "library_files", "include_dirs", "defines", "parameters"}
)

CompileInput: TypeAlias = Union[Sequence[str | Path], "CompileManifest"]


@dataclass(frozen=True, slots=True)
class NamedValue:
    name: str
    value: str | None

    @property
    def text(self) -> str:
        return self.name if self.value is None else f"{self.name}={self.value}"


@dataclass(frozen=True, slots=True)
class InputSnapshot:
    path: Path
    display_path: str
    logical_path: str
    content_hash: str
    role: str


@dataclass(frozen=True, slots=True)
class CompileManifest:
    """Normalized, content-bound compile inputs.

    The historical ``SourceBundle`` name remains an alias for this class. New
    code should use ``CompileManifest`` to make the wider contract explicit.
    """

    sources: tuple[Path, ...]
    library_files: tuple[Path, ...]
    include_dirs: tuple[Path, ...]
    defines: tuple[NamedValue, ...]
    parameters: tuple[NamedValue, ...]
    language: str
    top: str
    snapshots: tuple[InputSnapshot, ...]
    manifest_path: Path | None = None

    @classmethod
    def create(
        cls,
        sources: Sequence[str | Path],
        top: str,
        *,
        language: str = "systemverilog",
        library_files: Sequence[str | Path] = (),
        include_dirs: Sequence[str | Path] = (),
        defines: Sequence[str] = (),
        parameters: Sequence[str] = (),
        manifest_path: str | Path | None = None,
    ) -> "CompileManifest":
        validate_compile_identifier(top, "top")
        if language not in _LANGUAGES:
            raise RtlAssError(
                "invalid_compile_language",
                "compile language must be systemverilog or verilog-2005",
                {"language": language},
            )
        source_paths, source_display = _resolve_files(sources, "source", required=True)
        library_paths, library_display = _resolve_files(library_files, "library_file", required=False)
        combined = (*source_paths, *library_paths)
        if len(set(combined)) != len(combined):
            raise RtlAssError("duplicate_compile_input", "sources and library files must be distinct")
        if language == "verilog-2005":
            systemverilog = [str(path) for path in combined if path.suffix.lower() == ".sv"]
            if systemverilog:
                raise RtlAssError(
                    "language_source_mismatch",
                    "verilog-2005 manifests cannot contain .sv compilation units",
                    {"paths": systemverilog},
                )
        resolved_includes, include_display = _resolve_include_dirs(include_dirs)
        normalized_defines = _parse_named_values(defines, field="define", allow_empty=True)
        normalized_parameters = _parse_named_values(parameters, field="parameter", allow_empty=False)
        manifest_source = Path(manifest_path) if manifest_path is not None else None
        manifest = manifest_source.resolve() if manifest_source is not None else None
        if manifest is not None and (
            not manifest.is_file() or (manifest_source is not None and manifest_source.is_symlink())
        ):
            raise RtlAssError("invalid_compile_manifest", "compile manifest must be a regular non-symlink file")

        snapshots: list[InputSnapshot] = []
        seen: set[Path] = set()
        for role, paths, displays in (
            ("source", source_paths, source_display),
            ("library", library_paths, library_display),
        ):
            for index, (path, display) in enumerate(zip(paths, displays, strict=True)):
                snapshots.append(InputSnapshot(path, display, f"{role}/{index}", hash_file(path), role))
                seen.add(path)
        include_file_count = 0
        include_bytes = 0
        for root_index, (root, display_root) in enumerate(zip(resolved_includes, include_display, strict=True)):
            for path in _iter_include_files(root):
                if path in seen:
                    continue
                include_file_count += 1
                include_bytes += path.stat().st_size
                if include_file_count > MAX_INCLUDE_FILES or include_bytes > MAX_INCLUDE_BYTES:
                    raise RtlAssError(
                        "include_snapshot_too_large",
                        "combined include directory snapshot exceeds the audited limits",
                        {"max_files": MAX_INCLUDE_FILES, "max_bytes": MAX_INCLUDE_BYTES},
                    )
                relative = path.relative_to(root).as_posix()
                display = (Path(display_root) / relative).as_posix()
                snapshots.append(
                    InputSnapshot(path, display, f"include/{root_index}/{relative}", hash_file(path), "include")
                )
                seen.add(path)
        if manifest is not None and manifest_source is not None and manifest not in seen:
            snapshots.append(
                InputSnapshot(manifest, manifest_source.as_posix(), "manifest/0", hash_file(manifest), "manifest")
            )

        return cls(
            sources=source_paths,
            library_files=library_paths,
            include_dirs=resolved_includes,
            defines=normalized_defines,
            parameters=normalized_parameters,
            language=language,
            top=top,
            snapshots=tuple(snapshots),
            manifest_path=manifest,
        )

    @classmethod
    def load(cls, path: str | Path) -> "CompileManifest":
        manifest_path = Path(path)
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise RtlAssError("invalid_compile_manifest", "compile manifest must be a regular non-symlink file")
        if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
            raise RtlAssError(
                "compile_manifest_too_large",
                "compile manifest exceeds the audited byte limit",
                {"max_bytes": MAX_MANIFEST_BYTES},
            )
        try:
            value = parse_json(read_utf8_exact(manifest_path))
        except (UnicodeDecodeError, ValueError) as exc:
            raise RtlAssError(
                "invalid_compile_manifest", "compile manifest must contain strict UTF-8 JSON", {"path": str(path)}
            ) from exc
        if not isinstance(value, dict) or set(value) != _MANIFEST_KEYS:
            raise RtlAssError(
                "invalid_compile_manifest",
                "compile manifest keys do not match the versioned contract",
                {"required_keys": sorted(_MANIFEST_KEYS)},
            )
        if value.get("schema_version") != COMPILE_MANIFEST_SCHEMA_VERSION:
            raise RtlAssError("invalid_compile_manifest", "unsupported compile manifest schema version")
        root = manifest_path.resolve().parent
        sources = _manifest_paths(value.get("sources"), root, "sources", required=True)
        libraries = _manifest_paths(value.get("library_files"), root, "library_files", required=False)
        includes = _manifest_paths(value.get("include_dirs"), root, "include_dirs", required=False)
        defines = _manifest_mapping(value.get("defines"), "defines", allow_null=True)
        parameters = _manifest_mapping(value.get("parameters"), "parameters", allow_null=False)
        top = value.get("top")
        language = value.get("language")
        if not isinstance(top, str) or not isinstance(language, str):
            raise RtlAssError("invalid_compile_manifest", "top and language must be strings")
        return cls.create(
            sources,
            top,
            language=language,
            library_files=libraries,
            include_dirs=includes,
            defines=defines,
            parameters=parameters,
            manifest_path=manifest_path,
        )

    @property
    def compilation_units(self) -> tuple[Path, ...]:
        return (*self.sources, *self.library_files)

    @property
    def display_paths(self) -> tuple[str, ...]:
        return tuple(snapshot.display_path for snapshot in self.snapshots if snapshot.role == "source")

    @property
    def content_hashes(self) -> tuple[str, ...]:
        return tuple(snapshot.content_hash for snapshot in self.snapshots if snapshot.role == "source")

    @property
    def source_hashes(self) -> list[dict[str, Any]]:
        return [
            {"index": index, "path": snapshot.display_path, "content_hash": snapshot.content_hash}
            for index, snapshot in enumerate(item for item in self.snapshots if item.role == "source")
        ]

    @property
    def subject_hashes(self) -> list[dict[str, Any]]:
        return [
            {"index": index, "path": item.display_path, "content_hash": item.content_hash}
            for index, item in enumerate(self.snapshots)
        ]

    @property
    def input_hash(self) -> str:
        inputs = [
            {
                "index": index,
                "role": item.role,
                "logical_path": item.logical_path,
                "content_hash": item.content_hash,
            }
            for index, item in enumerate(self.snapshots)
        ]
        return hash_json(
            {
                "schema_version": COMPILE_MANIFEST_SCHEMA_VERSION,
                "top": self.top,
                "language": self.language,
                "inputs": inputs,
                "defines": [item.text for item in self.defines],
                "parameters": [item.text for item in self.parameters],
            }
        )

    def inputs_unchanged(self) -> bool:
        try:
            current = CompileManifest.create(
                self.sources,
                self.top,
                language=self.language,
                library_files=self.library_files,
                include_dirs=self.include_dirs,
                defines=[item.text for item in self.defines],
                parameters=[item.text for item in self.parameters],
                manifest_path=self.manifest_path,
            )
        except RtlAssError:
            return False
        return current.input_hash == self.input_hash

    def summary(self) -> dict[str, Any]:
        return {
            "schema_version": COMPILE_MANIFEST_SCHEMA_VERSION,
            "top": self.top,
            "language": self.language,
            "source_count": len(self.sources),
            "library_file_count": len(self.library_files),
            "include_dir_count": len(self.include_dirs),
            "tracked_input_count": len(self.snapshots),
            "define_count": len(self.defines),
            "parameter_count": len(self.parameters),
            "input_hash": self.input_hash,
            "subject_hashes": self.subject_hashes,
        }

    def option_summary(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "source_count": len(self.sources),
            "library_file_count": len(self.library_files),
            "include_dir_count": len(self.include_dirs),
            "define_count": len(self.defines),
            "parameter_count": len(self.parameters),
            "tracked_input_count": len(self.snapshots),
        }


def coerce_compile_manifest(value: CompileInput, top: str | None) -> CompileManifest:
    if isinstance(value, CompileManifest):
        if top is not None and top != value.top:
            raise RtlAssError(
                "compile_top_mismatch",
                "explicit top does not match the supplied compile manifest",
                {"explicit_top": top, "manifest_top": value.top},
            )
        return value
    if top is None:
        raise RtlAssError("top_required", "top is required when sources are supplied without a compile manifest")
    return CompileManifest.create(value, top)


def verilator_compile_arguments(manifest: CompileManifest) -> list[str]:
    language = "1800-2017" if manifest.language == "systemverilog" else "1364-2005"
    return [
        "--language",
        language,
        *(f"-I{path}" for path in manifest.include_dirs),
        *(f"-D{item.text}" for item in manifest.defines),
        *(f"-G{item.text}" for item in manifest.parameters),
    ]


def iverilog_compile_arguments(manifest: CompileManifest) -> list[str]:
    generation = "-g2012" if manifest.language == "systemverilog" else "-g2005"
    return [
        generation,
        *(argument for path in manifest.include_dirs for argument in ("-I", str(path))),
        *(f"-D{item.text}" for item in manifest.defines),
        *(f"-P{manifest.top}.{item.text}" for item in manifest.parameters),
    ]


def yosys_read_command(manifest: CompileManifest, *, formal: bool = False) -> str:
    options = []
    if formal:
        options.append("-formal")
    if manifest.language == "systemverilog":
        options.append("-sv")
    for path in manifest.include_dirs:
        if any(character.isspace() for character in str(path)):
            raise RtlAssError(
                "unsupported_yosys_include_path",
                "Yosys read_verilog does not safely support whitespace in -I paths",
                {"path": str(path)},
            )
        options.append(f"-I{path}")
    options.extend(f"-D{item.text}" for item in manifest.defines)
    files = [_yosys_quote(str(path)) for path in manifest.compilation_units]
    return " ".join(("read_verilog", *options, *files))


def yosys_parameter_commands(manifest: CompileManifest) -> list[str]:
    return [f"chparam -set {item.name} {_yosys_quote(item.value or '')} {manifest.top}" for item in manifest.parameters]


def _yosys_quote(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise RtlAssError("invalid_compile_option", "Yosys compile values cannot contain line breaks")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _resolve_files(
    values: Sequence[str | Path], field: str, *, required: bool
) -> tuple[tuple[Path, ...], tuple[str, ...]]:
    provided = tuple(Path(value) for value in values)
    if len(provided) > MAX_COMPILE_FILES:
        raise RtlAssError(
            "too_many_compile_inputs",
            "compile file list exceeds the audited limit",
            {"field": field, "max_files": MAX_COMPILE_FILES},
        )
    displays = tuple(path.as_posix() for path in provided)
    resolved = tuple(path.resolve() for path in provided)
    if required and not resolved:
        raise RtlAssError("sources_required", "at least one RTL source is required")
    if len(set(resolved)) != len(resolved):
        raise RtlAssError("duplicate_compile_input", f"{field} list contains duplicate paths")
    invalid = [
        str(path)
        for source, path in zip(provided, resolved, strict=True)
        if source.is_symlink() or not path.is_file() or path.suffix.lower() not in RTL_SUFFIXES
    ]
    if invalid:
        raise RtlAssError(
            "invalid_compile_input",
            "compile inputs must be regular non-symlink Verilog/SystemVerilog files",
            {"field": field, "paths": invalid},
        )
    return resolved, displays


def _resolve_include_dirs(values: Sequence[str | Path]) -> tuple[tuple[Path, ...], tuple[str, ...]]:
    provided = tuple(Path(value) for value in values)
    if len(provided) > MAX_INCLUDE_DIRS:
        raise RtlAssError(
            "too_many_include_directories",
            "include directory list exceeds the audited limit",
            {"max_directories": MAX_INCLUDE_DIRS},
        )
    displays = tuple(path.as_posix() for path in provided)
    resolved = tuple(path.resolve() for path in provided)
    if len(set(resolved)) != len(resolved):
        raise RtlAssError("duplicate_compile_input", "include directory list contains duplicate paths")
    invalid = [
        str(path) for source, path in zip(provided, resolved, strict=True) if source.is_symlink() or not path.is_dir()
    ]
    if invalid:
        raise RtlAssError(
            "invalid_include_directory",
            "include directories must be existing non-symlink directories",
            {"paths": invalid},
        )
    return resolved, displays


def _iter_include_files(root: Path) -> Iterator[Path]:
    for current, directories, files in os.walk(root, onerror=_raise_walk_error):
        directories.sort()
        files.sort()
        current_path = Path(current)
        for name in directories:
            path = current_path / name
            if path.is_symlink():
                raise RtlAssError(
                    "include_symlink_not_allowed",
                    "include directory snapshots cannot contain symbolic links",
                    {"path": str(path)},
                )
        for name in files:
            path = current_path / name
            if path.is_symlink():
                raise RtlAssError(
                    "include_symlink_not_allowed",
                    "include directory snapshots cannot contain symbolic links",
                    {"path": str(path)},
                )
            if path.is_file():
                yield path.resolve()


def _raise_walk_error(error: OSError) -> None:
    raise error


def _parse_named_values(values: Sequence[str], *, field: str, allow_empty: bool) -> tuple[NamedValue, ...]:
    if len(values) > MAX_COMPILE_OPTIONS:
        raise RtlAssError(
            "too_many_compile_options",
            "compile option list exceeds the audited limit",
            {"field": field, "max_options": MAX_COMPILE_OPTIONS},
        )
    parsed: list[NamedValue] = []
    names: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            raise RtlAssError("invalid_compile_option", f"{field} values must be strings")
        name, separator, value = raw.partition("=")
        validate_compile_identifier(name, field)
        normalized_value = value if separator else None
        if normalized_value is None and not allow_empty:
            raise RtlAssError("invalid_compile_option", f"{field} requires NAME=VALUE")
        if normalized_value is not None and (not normalized_value or not _VALUE.fullmatch(normalized_value)):
            raise RtlAssError(
                "invalid_compile_option",
                f"{field} values must be bounded single-token expressions",
                {"name": name},
            )
        if name in names:
            raise RtlAssError("duplicate_compile_option", f"duplicate {field} name", {"name": name})
        names.add(name)
        parsed.append(NamedValue(name, normalized_value))
    return tuple(sorted(parsed, key=lambda item: item.name))


def validate_compile_identifier(value: str, field: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise RtlAssError(
            "invalid_compile_identifier", f"{field} must be a Verilog identifier", {"field": field, "value": value}
        )


def _manifest_paths(value: Any, root: Path, field: str, *, required: bool) -> list[Path]:
    if not isinstance(value, list) or (required and not value) or any(not isinstance(item, str) for item in value):
        raise RtlAssError("invalid_compile_manifest", f"{field} must be a list of relative paths")
    paths: list[Path] = []
    for item in value:
        if not item or len(item) > 4096 or "\x00" in item or "\n" in item or "\r" in item:
            raise RtlAssError(
                "invalid_compile_manifest",
                f"{field} entries must be nonempty bounded single-line paths",
            )
        relative = Path(item)
        if relative.is_absolute() or ".." in relative.parts or "\\" in item:
            raise RtlAssError(
                "compile_manifest_path_escape", "compile manifest paths must remain below its directory", {"path": item}
            )
        current = root
        for component in relative.parts:
            current /= component
            if current.is_symlink():
                raise RtlAssError(
                    "compile_manifest_symlink_not_allowed",
                    "compile manifest paths cannot traverse symbolic links",
                    {"path": item},
                )
        resolved = (root / relative).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise RtlAssError(
                "compile_manifest_path_escape", "compile manifest paths must remain below its directory", {"path": item}
            ) from exc
        paths.append(resolved)
    return paths


def _manifest_mapping(value: Any, field: str, *, allow_null: bool) -> list[str]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise RtlAssError("invalid_compile_manifest", f"{field} must be an object")
    result: list[str] = []
    for name in sorted(value):
        item = value[name]
        if item is None and allow_null:
            result.append(name)
        elif isinstance(item, str):
            result.append(f"{name}={item}")
        else:
            raise RtlAssError(
                "invalid_compile_manifest", f"{field} values must be strings" + (" or null" if allow_null else "")
            )
    return result
