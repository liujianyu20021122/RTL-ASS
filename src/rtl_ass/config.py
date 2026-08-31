"""Local RTL-ASS configuration."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rtl_ass.errors import RtlAssError
from rtl_ass.kb.gates import normalize_evidence_kinds
from rtl_ass.kb.models import RecordRole, validate_identifier


@dataclass(frozen=True, slots=True)
class VerificationGate:
    role: RecordRole
    required_kinds: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Settings:
    database: Path = Path(".rtl-ass/index.db")
    default_namespace: str = "project:default"
    search_limit: int = 5
    max_source_bytes: int = 5 * 1024 * 1024
    follow_symlinks: bool = False
    verification_gates: tuple[VerificationGate, ...] = ()

    def required_evidence_kinds(self, role: RecordRole) -> tuple[str, ...]:
        return next((gate.required_kinds for gate in self.verification_gates if gate.role is role), ())


def load_settings(path: str | Path | None = None) -> Settings:
    if path is None:
        return Settings()
    config_path = Path(path)
    if not config_path.is_file():
        raise RtlAssError("config_not_found", "configuration file does not exist", {"path": str(config_path)})
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise RtlAssError("invalid_config", "configuration file is not valid UTF-8 TOML", {"reason": str(exc)}) from exc
    _reject_unknown_keys(data, {"schema_version", "knowledge", "project", "verification"}, "root")
    if data.get("schema_version") != 1:
        raise RtlAssError("invalid_config", "configuration schema_version must be 1")
    knowledge = _table(data, "knowledge")
    project = _table(data, "project")
    verification = _table(data, "verification")
    _reject_unknown_keys(knowledge, {"database", "default_namespace", "search_limit"}, "knowledge")
    _reject_unknown_keys(project, {"max_source_bytes", "follow_symlinks"}, "project")
    _reject_unknown_keys(verification, {"gates"}, "verification")

    database = _string(knowledge, "database", ".rtl-ass/index.db")
    namespace = validate_identifier(_string(knowledge, "default_namespace", "project:default"), "default_namespace")
    search_limit = _integer(knowledge, "search_limit", 5, minimum=1, maximum=50)
    max_source_bytes = _integer(project, "max_source_bytes", 5 * 1024 * 1024, minimum=1, maximum=100 * 1024 * 1024)
    follow_symlinks = _boolean(project, "follow_symlinks", False)
    gates = _verification_gates(verification.get("gates", {}))
    return Settings(
        database=Path(database),
        default_namespace=namespace,
        search_limit=search_limit,
        max_source_bytes=max_source_bytes,
        follow_symlinks=follow_symlinks,
        verification_gates=gates,
    )


def _table(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise RtlAssError("invalid_config", f"{key} must be a TOML table")
    return value


def _reject_unknown_keys(data: dict[str, Any], allowed: set[str], section: str) -> None:
    unknown = sorted(set(data).difference(allowed))
    if unknown:
        raise RtlAssError(
            "unknown_config_key", "configuration contains unsupported keys", {"section": section, "keys": unknown}
        )


def _string(data: dict[str, Any], key: str, default: str) -> str:
    value = data.get(key, default)
    if not isinstance(value, str) or not value:
        raise RtlAssError("invalid_config", f"{key} must be a non-empty string")
    return value


def _integer(data: dict[str, Any], key: str, default: int, *, minimum: int, maximum: int) -> int:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise RtlAssError("invalid_config", f"{key} must be an integer between {minimum} and {maximum}")
    return value


def _boolean(data: dict[str, Any], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise RtlAssError("invalid_config", f"{key} must be a boolean")
    return value


def _verification_gates(value: Any) -> tuple[VerificationGate, ...]:
    if not isinstance(value, dict):
        raise RtlAssError("invalid_config", "verification.gates must be a TOML table")
    gates: list[VerificationGate] = []
    for role_name in sorted(value):
        try:
            role = RecordRole(role_name)
        except ValueError as exc:
            raise RtlAssError(
                "invalid_verification_role",
                "verification gate names must be knowledge record roles",
                {"role": role_name},
            ) from exc
        gate = value[role_name]
        if not isinstance(gate, dict):
            raise RtlAssError("invalid_config", "each verification gate must be a TOML table", {"role": role_name})
        _reject_unknown_keys(gate, {"required_kinds"}, f"verification.gates.{role_name}")
        kinds = gate.get("required_kinds")
        if not isinstance(kinds, list) or not kinds:
            raise RtlAssError(
                "invalid_config",
                "verification gate required_kinds must be a non-empty array",
                {"role": role_name},
            )
        gates.append(VerificationGate(role=role, required_kinds=normalize_evidence_kinds(kinds)))
    return tuple(gates)
