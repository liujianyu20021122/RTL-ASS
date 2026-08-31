"""Reproducible file-level corpus locking and atomic knowledge import."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from rtl_ass.errors import RtlAssError
from rtl_ass.integrity import hash_bytes, hash_file, hash_json, parse_json, read_utf8_exact
from rtl_ass.kb.database import KnowledgeDatabase
from rtl_ass.kb.models import KnowledgeRecordInput, LicenseStatus, RecordRole, RecordStatus, validate_identifier
from rtl_ass.project import RTL_SUFFIXES, analyze_source

_MAX_POLICY_BYTES = 1024 * 1024
_MAX_LOCK_BYTES = 16 * 1024 * 1024
_MAX_REPOSITORIES = 64
_VALID_DECISIONS = frozenset({"include", "exclude"})
_VALID_SELECTION_KINDS = frozenset({"file", "prefix"})


def _object_file(path: str | Path, *, max_bytes: int, label: str) -> tuple[Path, dict[str, Any]]:
    source = Path(path)
    if not source.is_file():
        raise RtlAssError(f"{label}_not_found", f"{label} file does not exist", {"path": str(path)})
    if source.stat().st_size > max_bytes:
        raise RtlAssError(f"{label}_too_large", f"{label} exceeds its byte limit", {"max_bytes": max_bytes})
    try:
        value = parse_json(read_utf8_exact(source))
    except (ValueError, UnicodeDecodeError) as exc:
        raise RtlAssError(f"invalid_{label}", f"{label} must be finite UTF-8 JSON", {"reason": str(exc)}) from exc
    if not isinstance(value, dict):
        raise RtlAssError(f"invalid_{label}", f"{label} root must be an object")
    return source, value


def _require_keys(
    value: Mapping[str, Any],
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
    context: str,
) -> None:
    keys = frozenset(value)
    missing = sorted(required - keys)
    unknown = sorted(keys - required - optional)
    if missing or unknown:
        raise RtlAssError(
            "invalid_corpus_contract",
            "corpus contract has missing or unknown keys",
            {"context": context, "missing": missing, "unknown": unknown},
        )


def _bounded_int(value: Any, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum or value > maximum:
        raise RtlAssError(
            "invalid_corpus_limit",
            "corpus limit is outside the supported range",
            {"field": field, "minimum": minimum, "maximum": maximum, "value": value},
        )
    return value


def _nonempty_string(value: Any, *, field: str, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise RtlAssError(
            "invalid_corpus_field",
            "corpus text field must be non-empty and bounded",
            {"field": field, "maximum": maximum},
        )
    return value


def _repository_name(value: Any, *, field: str) -> str:
    name = _nonempty_string(value, field=field, maximum=128)
    if PurePosixPath(name).name != name:
        raise RtlAssError(
            "invalid_corpus_repository_name",
            "corpus repository names must be one path segment",
            {"field": field},
        )
    return validate_identifier(name, "source_name")


def _iso_date(value: Any, *, field: str) -> str:
    text = _nonempty_string(value, field=field, maximum=10)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise RtlAssError("invalid_corpus_date", "corpus review date must use ISO 8601", {"field": field}) from exc
    if parsed.isoformat() != text:
        raise RtlAssError("invalid_corpus_date", "corpus review date must use YYYY-MM-DD", {"field": field})
    return text


def _iso_timestamp(value: Any, *, field: str) -> str:
    text = _nonempty_string(value, field=field, maximum=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RtlAssError("invalid_corpus_date", "corpus timestamp must use ISO 8601", {"field": field}) from exc
    if "T" not in text or parsed.tzinfo is None:
        raise RtlAssError(
            "invalid_corpus_date", "corpus timestamp requires ISO date-time syntax and a UTC offset", {"field": field}
        )
    return text


def _sha256(value: Any, *, field: str) -> str:
    text = _nonempty_string(value, field=field, maximum=64)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise RtlAssError("invalid_corpus_hash", "corpus hash must be lowercase SHA-256", {"field": field})
    return text


def _git_revision(value: Any, *, field: str) -> str:
    text = _nonempty_string(value, field=field, maximum=64)
    if len(text) not in {40, 64} or any(char not in "0123456789abcdef" for char in text):
        raise RtlAssError("invalid_corpus_revision", "corpus revision must be a full Git object ID", {"field": field})
    return text


def _string_array(value: Any, *, field: str, maximum_items: int = 128) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > maximum_items
        or any(not isinstance(item, str) or not item or len(item) > 1024 for item in value)
    ):
        raise RtlAssError("invalid_corpus_field", "corpus field must be a bounded string array", {"field": field})
    return value


def _relative_path(value: Any, *, field: str, prefix: bool = False) -> str:
    text = _nonempty_string(value, field=field, maximum=1024)
    if "\\" in text or text.startswith("/") or (prefix and not text.endswith("/")):
        raise RtlAssError(
            "invalid_corpus_path", "corpus paths must be normalized POSIX-relative paths", {"field": field}
        )
    path = PurePosixPath(text)
    normalized = path.as_posix() + ("/" if prefix else "")
    if any(part in {"", ".", ".."} for part in path.parts) or text != normalized:
        raise RtlAssError(
            "invalid_corpus_path",
            "corpus paths must be canonical and cannot contain empty or traversal segments",
            {"field": field},
        )
    return normalized


def _git(repository: Path, arguments: Sequence[str], *, binary: bool = False) -> str | bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=not binary,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise RtlAssError(
            "corpus_git_timeout",
            "git metadata inspection exceeded its time limit",
            {"repository": repository.name, "arguments": list(arguments)},
        ) from exc
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace") if isinstance(result.stderr, bytes) else result.stderr
        raise RtlAssError(
            "corpus_git_failed",
            "failed to inspect a locked corpus repository",
            {"repository": repository.name, "arguments": list(arguments), "stderr": stderr.strip()},
        )
    if binary:
        if not isinstance(result.stdout, bytes):
            raise AssertionError("binary git output must be bytes")
        return result.stdout
    if not isinstance(result.stdout, str):
        raise AssertionError("text git output must be str")
    return result.stdout.strip()


def _tracked_files(repository: Path) -> tuple[str, ...]:
    output = _git(repository, ["ls-files", "-z"], binary=True)
    if not isinstance(output, bytes):
        raise AssertionError("tracked-file output must be bytes")
    try:
        files = tuple(item.decode("utf-8") for item in output.split(b"\0") if item)
    except UnicodeDecodeError as exc:
        raise RtlAssError(
            "invalid_corpus_filename",
            "tracked corpus filenames must be UTF-8",
            {"repository": repository.name, "offset": exc.start},
        ) from exc
    return tuple(sorted(files))


def _validate_repository(
    repository: Path,
    *,
    source_uri: str,
    revision: str,
    license_path: str,
    license_hash: str,
) -> frozenset[str]:
    if repository.is_symlink() or (repository / ".git").is_symlink() or not (repository / ".git").is_dir():
        raise RtlAssError(
            "invalid_corpus_repository",
            "locked corpus source must be a direct Git checkout",
            {"repository": repository.name},
        )
    actual_revision = _git(repository, ["rev-parse", "HEAD"])
    actual_origin = _git(repository, ["remote", "get-url", "origin"])
    dirty = _git(repository, ["status", "--porcelain", "--untracked-files=no"])
    if actual_revision != revision or actual_origin != source_uri or dirty:
        raise RtlAssError(
            "corpus_repository_mismatch",
            "corpus checkout does not match the reviewed source identity",
            {
                "repository": repository.name,
                "expected_revision": revision,
                "actual_revision": actual_revision,
                "expected_origin": source_uri,
                "actual_origin": actual_origin,
                "tracked_changes": bool(dirty),
            },
        )
    tracked = frozenset(_tracked_files(repository))
    if license_path not in tracked:
        raise RtlAssError(
            "corpus_license_untracked",
            "reviewed corpus license file must be tracked by the pinned revision",
            {"repository": repository.name, "license_path": license_path},
        )
    license_file = repository / license_path
    if not license_file.is_file() or license_file.is_symlink() or hash_file(license_file) != license_hash:
        raise RtlAssError(
            "corpus_license_mismatch",
            "reviewed corpus license file is missing or changed",
            {"repository": repository.name, "license_path": license_path},
        )
    return tracked


def _source_index(upstream: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    _require_keys(
        upstream,
        required=frozenset({"schema_version", "generated_at", "source_root", "source_count", "sources", "policy"}),
        context="upstream manifest",
    )
    if upstream["schema_version"] != "1.0" or not isinstance(upstream["sources"], list):
        raise RtlAssError("invalid_corpus_contract", "unsupported upstream corpus manifest")
    result: dict[str, dict[str, Any]] = {}
    for item in upstream["sources"]:
        if not isinstance(item, dict):
            raise RtlAssError("invalid_corpus_contract", "upstream source entries must be objects")
        name = _repository_name(item.get("name"), field="upstream.sources.name")
        if name in result:
            raise RtlAssError(
                "duplicate_corpus_source", "upstream manifest contains a duplicate source", {"name": name}
            )
        result[name] = item
    if upstream["source_count"] != len(result):
        raise RtlAssError("invalid_corpus_contract", "upstream source_count does not match its entries")
    return result


def _policy_sources(policy: Mapping[str, Any], upstream_names: frozenset[str]) -> list[dict[str, Any]]:
    sources = policy.get("sources")
    if not isinstance(sources, list) or not 1 <= len(sources) <= _MAX_REPOSITORIES:
        raise RtlAssError("invalid_corpus_contract", "policy sources must be a bounded non-empty array")
    result: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, item in enumerate(sources):
        if not isinstance(item, dict):
            raise RtlAssError("invalid_corpus_contract", "policy source entries must be objects", {"index": index})
        decision = item.get("decision")
        required = {"name", "decision", "rationale"}
        if decision == "include":
            required.update({"namespace", "license_review", "selections"})
        _require_keys(item, required=frozenset(required), context=f"policy source {index}")
        name = _repository_name(item["name"], field="sources.name")
        if decision not in _VALID_DECISIONS:
            raise RtlAssError("invalid_corpus_decision", "corpus decision must be include or exclude", {"name": name})
        _nonempty_string(item["rationale"], field=f"sources.{name}.rationale")
        if name in names:
            raise RtlAssError("duplicate_corpus_source", "policy contains a duplicate source", {"name": name})
        names.add(name)
        result.append(item)
    if names != set(upstream_names):
        raise RtlAssError(
            "incomplete_corpus_policy",
            "policy must make an explicit decision for every upstream source",
            {"missing": sorted(upstream_names - names), "unknown": sorted(names - upstream_names)},
        )
    return result


def _selection_role(value: Any, *, context: str) -> RecordRole | str:
    if value in {"auto", "design-auto"}:
        return str(value)
    try:
        role = RecordRole(value)
    except (TypeError, ValueError) as exc:
        raise RtlAssError("invalid_corpus_role", "selection role is unsupported", {"context": context}) from exc
    if role is RecordRole.TOOL_EVIDENCE:
        raise RtlAssError(
            "invalid_corpus_role", "tool evidence cannot be selected as source corpus", {"context": context}
        )
    return role


def _selected_files(source: Mapping[str, Any], tracked: frozenset[str]) -> dict[str, RecordRole | str]:
    selections = source["selections"]
    if not isinstance(selections, list) or not 1 <= len(selections) <= 128:
        raise RtlAssError("invalid_corpus_selection", "included sources require 1 to 128 selections")
    selected: dict[str, RecordRole | str] = {}
    for index, selection in enumerate(selections):
        if not isinstance(selection, dict):
            raise RtlAssError("invalid_corpus_selection", "selections must be objects")
        _require_keys(
            selection,
            required=frozenset({"kind", "path", "role"}),
            context=f"selection {source['name']}:{index}",
        )
        kind = selection["kind"]
        if kind not in _VALID_SELECTION_KINDS:
            raise RtlAssError("invalid_corpus_selection", "selection kind must be file or prefix")
        selection_path = _relative_path(
            selection["path"], field=f"selections.{source['name']}.path", prefix=kind == "prefix"
        )
        role = _selection_role(selection["role"], context=f"{source['name']}:{selection_path}")
        matches = [
            path
            for path in tracked
            if (path == selection_path if kind == "file" else path.startswith(selection_path))
            and Path(path).suffix.lower() in RTL_SUFFIXES
        ]
        if not matches:
            raise RtlAssError(
                "empty_corpus_selection",
                "corpus selection matched no tracked HDL files",
                {"repository": source["name"], "path": selection_path},
            )
        overlap = sorted(path for path in matches if path in selected)
        if overlap:
            raise RtlAssError(
                "overlapping_corpus_selection",
                "one corpus file matched multiple selections",
                {"repository": source["name"], "paths": overlap[:20]},
            )
        selected.update((path, role) for path in matches)
    return dict(sorted(selected.items()))


def _license_review(source: Mapping[str, Any], upstream: Mapping[str, Any]) -> dict[str, str]:
    review = source["license_review"]
    if not isinstance(review, dict):
        raise RtlAssError("invalid_corpus_license_review", "license review must be an object")
    _require_keys(
        review,
        required=frozenset({"spdx", "license_path", "license_hash", "reviewed_by", "reviewed_at", "scope"}),
        context=f"license review {source['name']}",
    )
    normalized = {
        key: _nonempty_string(review[key], field=f"license_review.{key}", maximum=1024)
        for key in ("spdx", "license_path", "license_hash", "reviewed_by", "scope")
    }
    normalized["reviewed_at"] = _iso_date(review["reviewed_at"], field="license_review.reviewed_at")
    finding = upstream.get("license_finding")
    if not isinstance(finding, dict) or finding.get("status") != "detected":
        raise RtlAssError("corpus_license_unreviewable", "included corpus source lacks a detected license")
    expected = {
        "spdx": finding.get("spdx_candidate"),
        "license_path": finding.get("path"),
        "license_hash": finding.get("content_hash"),
    }
    if any(normalized[key] != expected[key] for key in expected):
        raise RtlAssError(
            "corpus_license_review_mismatch",
            "manual license review does not match the audited upstream license",
            {"repository": source["name"]},
        )
    _relative_path(normalized["license_path"], field="license_review.license_path")
    _sha256(normalized["license_hash"], field="license_review.license_hash")
    return normalized


def build_corpus_lock(policy_path: str | Path, *, source_root: str | Path | None = None) -> dict[str, Any]:
    policy_file, policy = _object_file(policy_path, max_bytes=_MAX_POLICY_BYTES, label="corpus_policy")
    _require_keys(
        policy,
        required=frozenset(
            {"schema_version", "lock_created_at", "upstream_manifest", "source_root", "limits", "sources"}
        ),
        context="corpus policy",
    )
    if policy["schema_version"] != "1.0":
        raise RtlAssError("invalid_corpus_contract", "unsupported corpus policy schema version")
    lock_created_at = _iso_timestamp(policy["lock_created_at"], field="lock_created_at")
    upstream_relative = _relative_path(policy["upstream_manifest"], field="upstream_manifest")
    project_root = policy_file.parent.parent.resolve()
    upstream_candidate = project_root / upstream_relative
    upstream_path = upstream_candidate.resolve()
    if upstream_candidate.is_symlink() or not upstream_path.is_relative_to(project_root):
        raise RtlAssError(
            "invalid_corpus_manifest_path",
            "upstream manifest must be a contained regular project file",
            {"path": upstream_relative},
        )
    _, upstream = _object_file(upstream_path, max_bytes=_MAX_POLICY_BYTES * 4, label="upstream_manifest")
    upstream_index = _source_index(upstream)
    policy_sources = _policy_sources(policy, frozenset(upstream_index))

    limits = policy["limits"]
    if not isinstance(limits, dict):
        raise RtlAssError("invalid_corpus_contract", "corpus limits must be an object")
    _require_keys(
        limits,
        required=frozenset({"max_files", "max_total_bytes", "max_source_bytes"}),
        context="corpus limits",
    )
    max_files = _bounded_int(limits["max_files"], field="max_files", minimum=1, maximum=100_000)
    max_total_bytes = _bounded_int(
        limits["max_total_bytes"], field="max_total_bytes", minimum=1, maximum=1024 * 1024 * 1024
    )
    max_source_bytes = _bounded_int(
        limits["max_source_bytes"], field="max_source_bytes", minimum=1, maximum=32 * 1024 * 1024
    )
    configured_root = _relative_path(policy["source_root"], field="source_root")
    root = (
        Path(source_root).resolve()
        if source_root is not None
        else (policy_file.parent.parent / configured_root).resolve()
    )
    if not root.is_dir() or root.is_symlink():
        raise RtlAssError("corpus_not_found", "corpus source root must be a direct directory", {"path": str(root)})

    repositories: list[dict[str, Any]] = []
    namespaces: set[str] = set()
    total_files = 0
    total_bytes = 0
    for source in policy_sources:
        if source["decision"] == "exclude":
            continue
        name = source["name"]
        upstream_source = upstream_index[name]
        if (
            upstream_source.get("source_kind") != "git"
            or not upstream_source.get("reproducibly_pinned")
            or upstream_source.get("benchmark_contamination_risk") != "not_detected"
        ):
            raise RtlAssError(
                "corpus_source_not_eligible",
                "included source must be pinned Git content without detected benchmark contamination",
                {"repository": name},
            )
        namespace = validate_identifier(
            _nonempty_string(source["namespace"], field=f"sources.{name}.namespace", maximum=128), "namespace"
        )
        if namespace in namespaces:
            raise RtlAssError(
                "duplicate_corpus_namespace",
                "each included corpus source requires an isolated namespace",
                {"namespace": namespace},
            )
        namespaces.add(namespace)
        review = _license_review(source, upstream_source)
        source_uri = _nonempty_string(upstream_source.get("source_uri"), field=f"upstream.{name}.source_uri")
        revision = _git_revision(upstream_source.get("revision"), field=f"upstream.{name}.revision")
        source_identity = _sha256(upstream_source.get("source_identity"), field=f"upstream.{name}.source_identity")
        repository = root / name
        tracked = _validate_repository(
            repository,
            source_uri=source_uri,
            revision=revision,
            license_path=review["license_path"],
            license_hash=review["license_hash"],
        )
        selected = _selected_files(source, tracked)
        locked_files: list[dict[str, Any]] = []
        for relative, override in selected.items():
            candidate = repository / relative
            if (
                candidate.is_symlink()
                or not candidate.is_file()
                or not candidate.resolve().is_relative_to(repository.resolve())
            ):
                raise RtlAssError(
                    "invalid_corpus_file",
                    "selected corpus path must be a contained regular file",
                    {"repository": name, "path": relative},
                )
            byte_count = candidate.stat().st_size
            if byte_count > max_source_bytes:
                raise RtlAssError(
                    "corpus_source_too_large",
                    "selected corpus file exceeds its byte limit",
                    {"repository": name, "path": relative, "byte_count": byte_count},
                )
            try:
                content = read_utf8_exact(candidate)
            except UnicodeDecodeError as exc:
                raise RtlAssError(
                    "invalid_corpus_encoding",
                    "selected corpus HDL must be UTF-8",
                    {"repository": name, "path": relative, "offset": exc.start},
                ) from exc
            inspection = analyze_source(candidate, content, relative)
            inspected_role = RecordRole(inspection["role"])
            if override == "auto":
                role = inspected_role
            elif override == "design-auto":
                role = (
                    inspected_role
                    if inspected_role in {RecordRole.PACKAGE, RecordRole.INTERFACE}
                    else RecordRole.RTL_DESIGN
                )
            else:
                if not isinstance(override, RecordRole):
                    raise AssertionError("validated corpus role override must be a RecordRole")
                role = override
            named_units = inspection["modules"] or inspection["interfaces"] or inspection["packages"]
            title = ", ".join(named_units) if named_units else relative
            summary = f"{inspection['language']} {role.value} from {name}:{relative}"
            locked_files.append(
                {
                    "path": relative,
                    "content_hash": hash_bytes(content.encode("utf-8")),
                    "byte_count": byte_count,
                    "role": role.value,
                    "language": inspection["language"],
                    "title": title,
                    "summary": summary,
                    "inspection": inspection,
                }
            )
            total_files += 1
            total_bytes += byte_count
            if total_files > max_files or total_bytes > max_total_bytes:
                raise RtlAssError(
                    "corpus_limit_exceeded",
                    "selected corpus exceeds the reviewed aggregate limits",
                    {"file_count": total_files, "byte_count": total_bytes},
                )
        repositories.append(
            {
                "name": name,
                "namespace": namespace,
                "source_uri": source_uri,
                "revision": revision,
                "source_identity": source_identity,
                "rationale": source["rationale"],
                "license_review": review,
                "files": locked_files,
            }
        )
    lock: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": lock_created_at,
        "source_root": configured_root,
        "upstream_manifest_hash": hash_file(upstream_path),
        "policy_hash": hash_file(policy_file),
        "limits": {
            "max_files": max_files,
            "max_total_bytes": max_total_bytes,
            "max_source_bytes": max_source_bytes,
        },
        "repository_count": len(repositories),
        "file_count": total_files,
        "byte_count": total_bytes,
        "repositories": repositories,
    }
    lock["lock_hash"] = hash_json(lock)
    return lock


def write_corpus_lock(lock: Mapping[str, Any], output_path: str | Path) -> Path:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(
        json.dumps(dict(lock), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, destination)
    return destination


def _validate_locked_license_review(value: Any, *, repository: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RtlAssError("invalid_corpus_lock", "locked license review must be an object")
    _require_keys(
        value,
        required=frozenset({"spdx", "license_path", "license_hash", "reviewed_by", "reviewed_at", "scope"}),
        context=f"locked license review {repository}",
    )
    _nonempty_string(value["spdx"], field="license_review.spdx", maximum=128)
    _relative_path(value["license_path"], field="license_review.license_path")
    _sha256(value["license_hash"], field="license_review.license_hash")
    _nonempty_string(value["reviewed_by"], field="license_review.reviewed_by", maximum=128)
    _iso_date(value["reviewed_at"], field="license_review.reviewed_at")
    _nonempty_string(value["scope"], field="license_review.scope", maximum=1024)
    return value


def _validate_locked_inspection(item: Mapping[str, Any], *, path: str, byte_count: int) -> None:
    inspection = item["inspection"]
    if not isinstance(inspection, dict):
        raise RtlAssError("invalid_corpus_lock", "locked inspection must be an object")
    _require_keys(
        inspection,
        required=frozenset(
            {
                "path",
                "language",
                "content_hash",
                "byte_count",
                "role",
                "role_confidence",
                "role_basis",
                "modules",
                "interfaces",
                "packages",
                "includes",
                "clock_hints",
                "reset_hints",
            }
        ),
        context=f"locked inspection {path}",
    )
    if inspection["path"] != path or inspection["byte_count"] != byte_count:
        raise RtlAssError("invalid_corpus_lock", "locked inspection identity does not match its file", {"path": path})
    if inspection["content_hash"] != item["content_hash"] or inspection["language"] != item["language"]:
        raise RtlAssError("invalid_corpus_lock", "locked inspection content metadata is inconsistent", {"path": path})
    try:
        inspected_role = RecordRole(inspection["role"])
    except (TypeError, ValueError) as exc:
        raise RtlAssError("invalid_corpus_lock", "locked inspection role is unsupported", {"path": path}) from exc
    if inspected_role is RecordRole.TOOL_EVIDENCE or inspection["role_confidence"] not in {"medium", "high"}:
        raise RtlAssError("invalid_corpus_lock", "locked inspection classification is unsupported", {"path": path})
    for field in ("role_basis", "modules", "interfaces", "packages", "includes", "clock_hints", "reset_hints"):
        _string_array(inspection[field], field=f"inspection.{field}")


def load_corpus_lock(path: str | Path) -> dict[str, Any]:
    _, lock = _object_file(path, max_bytes=_MAX_LOCK_BYTES, label="corpus_lock")
    _require_keys(
        lock,
        required=frozenset(
            {
                "schema_version",
                "generated_at",
                "source_root",
                "upstream_manifest_hash",
                "policy_hash",
                "limits",
                "repository_count",
                "file_count",
                "byte_count",
                "repositories",
                "lock_hash",
            }
        ),
        context="corpus lock",
    )
    if lock["schema_version"] != "1.0":
        raise RtlAssError("invalid_corpus_lock", "unsupported corpus lock schema version")
    _iso_timestamp(lock["generated_at"], field="generated_at")
    _relative_path(lock["source_root"], field="source_root")
    _sha256(lock["upstream_manifest_hash"], field="upstream_manifest_hash")
    _sha256(lock["policy_hash"], field="policy_hash")
    claimed_hash = lock["lock_hash"]
    payload = dict(lock)
    payload.pop("lock_hash")
    if not isinstance(claimed_hash, str) or claimed_hash != hash_json(payload):
        raise RtlAssError("corpus_lock_hash_mismatch", "corpus lock identity does not match its content")
    _sha256(claimed_hash, field="lock_hash")
    repositories = lock["repositories"]
    repository_count = _bounded_int(
        lock["repository_count"], field="repository_count", minimum=1, maximum=_MAX_REPOSITORIES
    )
    if not isinstance(repositories, list) or repository_count != len(repositories):
        raise RtlAssError("invalid_corpus_lock", "corpus repository count is inconsistent")
    limits = lock["limits"]
    if not isinstance(limits, dict):
        raise RtlAssError("invalid_corpus_lock", "corpus lock limits must be an object")
    _require_keys(
        limits,
        required=frozenset({"max_files", "max_total_bytes", "max_source_bytes"}),
        context="locked corpus limits",
    )
    max_files = _bounded_int(limits.get("max_files"), field="max_files", minimum=1, maximum=100_000)
    max_total_bytes = _bounded_int(
        limits.get("max_total_bytes"), field="max_total_bytes", minimum=1, maximum=1024 * 1024 * 1024
    )
    _bounded_int(limits.get("max_source_bytes"), field="max_source_bytes", minimum=1, maximum=32 * 1024 * 1024)
    file_count = _bounded_int(lock["file_count"], field="file_count", minimum=1, maximum=max_files)
    byte_count = _bounded_int(lock["byte_count"], field="byte_count", minimum=1, maximum=max_total_bytes)
    actual_files = 0
    actual_bytes = 0
    names: set[str] = set()
    namespaces: set[str] = set()
    for repository in repositories:
        if not isinstance(repository, dict):
            raise RtlAssError("invalid_corpus_lock", "locked repositories must be objects")
        _require_keys(
            repository,
            required=frozenset(
                {
                    "name",
                    "namespace",
                    "source_uri",
                    "revision",
                    "source_identity",
                    "rationale",
                    "license_review",
                    "files",
                }
            ),
            context="locked repository",
        )
        name = _repository_name(repository["name"], field="repositories.name")
        namespace = validate_identifier(
            _nonempty_string(repository["namespace"], field="repositories.namespace"), "namespace"
        )
        if namespace in namespaces:
            raise RtlAssError(
                "duplicate_corpus_namespace",
                "each locked corpus source requires an isolated namespace",
                {"namespace": namespace},
            )
        namespaces.add(namespace)
        _nonempty_string(repository["source_uri"], field=f"repositories.{name}.source_uri")
        _git_revision(repository["revision"], field=f"repositories.{name}.revision")
        _sha256(repository["source_identity"], field=f"repositories.{name}.source_identity")
        _nonempty_string(repository["rationale"], field=f"repositories.{name}.rationale")
        _validate_locked_license_review(repository["license_review"], repository=name)
        if name in names:
            raise RtlAssError("duplicate_corpus_source", "corpus lock contains a duplicate repository", {"name": name})
        names.add(name)
        files = repository["files"]
        if not isinstance(files, list) or not files:
            raise RtlAssError("invalid_corpus_lock", "locked repository must contain files", {"name": name})
        paths: set[str] = set()
        for item in files:
            if not isinstance(item, dict):
                raise RtlAssError("invalid_corpus_lock", "locked file entries must be objects")
            _require_keys(
                item,
                required=frozenset(
                    {"path", "content_hash", "byte_count", "role", "language", "title", "summary", "inspection"}
                ),
                context=f"locked file {name}",
            )
            path_value = _relative_path(item["path"], field="files.path")
            if path_value in paths or Path(path_value).suffix.lower() not in RTL_SUFFIXES:
                raise RtlAssError(
                    "invalid_corpus_lock", "locked file path is duplicate or not HDL", {"path": path_value}
                )
            paths.add(path_value)
            _sha256(item["content_hash"], field=f"files.{path_value}.content_hash")
            try:
                role = RecordRole(item["role"])
            except (TypeError, ValueError) as exc:
                raise RtlAssError(
                    "invalid_corpus_lock", "locked corpus role is unsupported", {"path": path_value}
                ) from exc
            if role is RecordRole.TOOL_EVIDENCE:
                raise RtlAssError("invalid_corpus_lock", "source corpus cannot contain tool-evidence records")
            if item["language"] not in {"verilog", "systemverilog"}:
                raise RtlAssError("invalid_corpus_lock", "locked HDL language is unsupported", {"path": path_value})
            _nonempty_string(item["title"], field=f"files.{path_value}.title", maximum=512)
            if not isinstance(item["summary"], str) or len(item["summary"]) > 4096:
                raise RtlAssError("invalid_corpus_lock", "locked summary must be a bounded string")
            current_bytes = _bounded_int(
                item["byte_count"], field="files.byte_count", minimum=1, maximum=limits["max_source_bytes"]
            )
            _validate_locked_inspection(item, path=path_value, byte_count=current_bytes)
            actual_files += 1
            actual_bytes += current_bytes
    if actual_files != file_count or actual_bytes != byte_count:
        raise RtlAssError(
            "invalid_corpus_lock",
            "corpus aggregate counts do not match locked files",
            {"actual_files": actual_files, "actual_bytes": actual_bytes},
        )
    return lock


def import_corpus_lock(
    database: KnowledgeDatabase,
    lock_path: str | Path,
    *,
    source_root: str | Path,
    actor: str,
) -> dict[str, Any]:
    validate_identifier(actor, "actor")
    lock = load_corpus_lock(lock_path)
    root = Path(source_root).resolve()
    if not root.is_dir() or root.is_symlink():
        raise RtlAssError("corpus_not_found", "corpus source root must be a direct directory", {"path": str(root)})
    records: list[KnowledgeRecordInput] = []
    source_counts: list[dict[str, Any]] = []
    for repository in lock["repositories"]:
        name = repository["name"]
        checkout = root / name
        review = repository["license_review"]
        tracked = _validate_repository(
            checkout,
            source_uri=repository["source_uri"],
            revision=repository["revision"],
            license_path=review["license_path"],
            license_hash=review["license_hash"],
        )
        role_counts: dict[str, int] = {}
        for item in repository["files"]:
            relative = item["path"]
            if relative not in tracked:
                raise RtlAssError(
                    "corpus_file_not_tracked",
                    "locked corpus file is no longer tracked",
                    {"repository": name, "path": relative},
                )
            candidate = checkout / relative
            if (
                candidate.is_symlink()
                or not candidate.is_file()
                or not candidate.resolve().is_relative_to(checkout.resolve())
            ):
                raise RtlAssError(
                    "invalid_corpus_file", "locked corpus path must remain a contained regular file", {"path": relative}
                )
            content_bytes = candidate.read_bytes()
            if len(content_bytes) != item["byte_count"] or hash_bytes(content_bytes) != item["content_hash"]:
                raise RtlAssError(
                    "corpus_file_hash_mismatch",
                    "locked corpus file content changed",
                    {"repository": name, "path": relative},
                )
            try:
                content = content_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise RtlAssError(
                    "invalid_corpus_encoding", "locked corpus HDL must remain UTF-8", {"path": relative}
                ) from exc
            role = RecordRole(item["role"])
            role_counts[role.value] = role_counts.get(role.value, 0) + 1
            records.append(
                KnowledgeRecordInput(
                    namespace=repository["namespace"],
                    role=role,
                    language=item["language"],
                    title=item["title"],
                    summary=item["summary"],
                    content=content,
                    source_uri=repository["source_uri"],
                    source_revision=repository["revision"],
                    source_path=relative,
                    license_spdx=review["spdx"],
                    license_status=LicenseStatus.KNOWN,
                    status=RecordStatus.RAW,
                    metadata={
                        "inspection": item["inspection"],
                        "corpus": {
                            "lock_hash": lock["lock_hash"],
                            "source_identity": repository["source_identity"],
                            "repository": name,
                            "trust_status": "quarantine",
                            "license_review": review,
                        },
                    },
                )
            )
        source_counts.append(
            {
                "name": name,
                "namespace": repository["namespace"],
                "record_count": len(repository["files"]),
                "role_counts": dict(sorted(role_counts.items())),
            }
        )
    stored = database.add_records(records, actor=actor)
    audit = database.verify_audit_chain()
    if not audit["valid"]:
        raise RtlAssError("corpus_audit_invalid", "database audit chain failed after corpus import", audit)
    return {
        "schema_version": "1.0",
        "lock_hash": lock["lock_hash"],
        "record_count": len(records),
        "created_count": sum(bool(item["created"]) for item in stored),
        "repeated_count": sum(not item["created"] for item in stored),
        "sources": source_counts,
        "audit_chain": audit,
    }
