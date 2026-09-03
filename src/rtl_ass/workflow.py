"""Task-scoped verification plans, evidence summaries, and CLI serialization."""

from __future__ import annotations

import os
import re
import stat
import time
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from rtl_ass.errors import RtlAssError
from rtl_ass.integrity import canonical_json, hash_file, hash_json, parse_json, read_utf8_exact
from rtl_ass.kb.gates import EVIDENCE_KINDS, validate_run_evidence
from rtl_ass.waveform import validate_waveform_evidence

_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_TASK_CLASSES = frozenset({"generation", "analysis", "debugging", "verification", "optimization"})
_REQUIREMENTS = frozenset({"required", "optional"})
_RUN_STATUSES = frozenset({"pass", "fail", "timeout", "blocked"})
_WAVE_STATUSES = frozenset({"complete", "found", "not_found"})
_PLAN_FIELDS = frozenset({"schema_version", "plan_id", "task_class", "claims", "stop_policy"})
_CLAIM_FIELDS = frozenset({"id", "statement", "evidence_kind", "requirement", "expected_status"})
_STOP_POLICY_FIELDS = frozenset({"max_retries_per_claim", "max_parallel_eda"})
_MAX_PLAN_BYTES = 256 * 1024
_MAX_EVIDENCE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class VerificationPlan:
    """Strict immutable view of a Codex-selected verification plan."""

    value: dict[str, Any]
    plan_hash: str

    @property
    def claims(self) -> tuple[dict[str, Any], ...]:
        return tuple(self.value["claims"])

    @property
    def claims_by_id(self) -> dict[str, dict[str, Any]]:
        return {claim["id"]: claim for claim in self.claims}

    def summary(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "plan_id": self.value["plan_id"],
            "plan_hash": self.plan_hash,
            "task_class": self.value["task_class"],
            "claim_count": len(self.claims),
            "required_claims": [claim["id"] for claim in self.claims if claim["requirement"] == "required"],
            "optional_claims": [claim["id"] for claim in self.claims if claim["requirement"] == "optional"],
            "stop_policy": dict(self.value["stop_policy"]),
        }


def load_verification_plan(path: str | Path) -> VerificationPlan:
    source = _regular_input_file(path, label="verification plan", max_bytes=_MAX_PLAN_BYTES)
    try:
        value = parse_json(read_utf8_exact(source))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RtlAssError("invalid_verification_plan", "verification plan must be one UTF-8 JSON object") from exc
    return validate_verification_plan(value)


def validate_verification_plan(value: object) -> VerificationPlan:
    if not isinstance(value, dict):
        raise RtlAssError("invalid_verification_plan", "verification plan root must be an object")
    try:
        canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise RtlAssError("invalid_verification_plan", "verification plan must contain finite JSON values") from exc
    if set(value) != _PLAN_FIELDS:
        raise RtlAssError(
            "invalid_verification_plan",
            "verification plan fields do not match the contract",
            {"missing": sorted(_PLAN_FIELDS.difference(value)), "unknown": sorted(set(value).difference(_PLAN_FIELDS))},
        )
    plan_id = value["plan_id"]
    task_class = value["task_class"]
    claims = value["claims"]
    stop_policy = value["stop_policy"]
    if value["schema_version"] != "1.0" or not isinstance(plan_id, str) or not _IDENTIFIER.fullmatch(plan_id):
        raise RtlAssError("invalid_verification_plan", "verification plan schema or identifier is invalid")
    if task_class not in _TASK_CLASSES:
        raise RtlAssError("invalid_verification_plan", "verification plan task class is unsupported")
    if not isinstance(claims, list) or not 1 <= len(claims) <= 16:
        raise RtlAssError("invalid_verification_plan", "verification plan requires between 1 and 16 claims")
    normalized_claims = [_validate_claim(claim, index=index) for index, claim in enumerate(claims)]
    claim_ids = [claim["id"] for claim in normalized_claims]
    if len(set(claim_ids)) != len(claim_ids):
        raise RtlAssError("invalid_verification_plan", "verification plan claim identifiers must be unique")
    if not any(claim["requirement"] == "required" for claim in normalized_claims):
        raise RtlAssError("invalid_verification_plan", "verification plan requires at least one required claim")
    normalized_policy = _validate_stop_policy(stop_policy)
    normalized = {
        "schema_version": "1.0",
        "plan_id": plan_id,
        "task_class": task_class,
        "claims": normalized_claims,
        "stop_policy": normalized_policy,
    }
    return VerificationPlan(normalized, hash_json(normalized))


def summarize_verification_plan(plan: VerificationPlan, evidence_links: Sequence[str]) -> dict[str, Any]:
    linked = _parse_evidence_links(plan, evidence_links)
    results: list[dict[str, Any]] = []
    identities: dict[tuple[str, str], set[str]] = {}
    retry_limit = plan.value["stop_policy"]["max_retries_per_claim"]
    for claim in plan.claims:
        attempts: list[dict[str, Any]] = []
        for path in linked.get(claim["id"], ()):
            attempt = _validate_claim_evidence(claim, path)
            attempts.append(attempt)
            identity = (attempt["evidence_kind"], attempt["input_hash"])
            identities.setdefault(identity, set()).add(attempt["evidence_file"])
        latest_status = attempts[-1]["status"] if attempts else "missing"
        satisfied = latest_status == claim["expected_status"]
        results.append(
            {
                "id": claim["id"],
                "statement": claim["statement"],
                "evidence_kind": claim["evidence_kind"],
                "requirement": claim["requirement"],
                "expected_status": claim["expected_status"],
                "status": latest_status,
                "satisfied": satisfied,
                "attempt_count": len(attempts),
                "retry_budget_exceeded": len(attempts) > retry_limit + 1,
                "attempts": attempts,
            }
        )
    duplicates = [
        {"evidence_kind": kind, "input_hash": input_hash, "evidence_files": sorted(paths)}
        for (kind, input_hash), paths in sorted(identities.items())
        if len(paths) > 1
    ]
    required = [result for result in results if result["requirement"] == "required"]
    ready = all(result["satisfied"] for result in required)
    return {
        "schema_version": "1.0",
        "plan_id": plan.value["plan_id"],
        "plan_hash": plan.plan_hash,
        "task_class": plan.value["task_class"],
        "ready_to_stop": ready,
        "stop_reason": "required_claims_satisfied" if ready else "required_claims_unsatisfied",
        "missing_required_claims": [result["id"] for result in required if result["status"] == "missing"],
        "unsatisfied_required_claims": [result["id"] for result in required if not result["satisfied"]],
        "duplicate_evidence_identities": duplicates,
        "retry_budget_exceeded_claims": [result["id"] for result in results if result["retry_budget_exceeded"]],
        "claims": results,
    }


@contextmanager
def verification_execution_lock(timeout_seconds: int, *, workspace: Path | None = None) -> Iterator[Path]:
    """Serialize high-cost CLI evidence runs inside one workspace."""

    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 0 <= timeout_seconds <= 3600:
        raise RtlAssError("invalid_lock_timeout", "lock timeout must be an integer between 0 and 3600 seconds")
    if os.name != "posix":
        raise RtlAssError(
            "verification_lock_unavailable",
            "the bounded workspace EDA lock currently requires a POSIX host",
        )
    import fcntl

    root = (workspace or Path.cwd()).resolve(strict=True)
    if not root.is_dir():
        raise RtlAssError("invalid_workspace", "verification lock workspace must be a directory")
    lock_directory = _safe_directory(root, ".rtl-ass")
    lock_directory = _safe_directory(lock_directory, "locks")
    lock_path = lock_directory / "verify.lock"
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise RtlAssError("verification_lock_unavailable", "cannot open the workspace verification lock") from exc
    acquired = False
    try:
        file_status = os.fstat(descriptor)
        if not stat.S_ISREG(file_status.st_mode) or file_status.st_nlink != 1:
            raise RtlAssError("verification_lock_unavailable", "workspace verification lock is not a regular file")
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise RtlAssError(
                        "verification_busy",
                        "another RTL-ASS evidence run holds the workspace lock",
                        {"lock": lock_path.relative_to(root).as_posix(), "timeout_seconds": timeout_seconds},
                    ) from exc
                time.sleep(0.05)
        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        os.fsync(descriptor)
        yield lock_path
    finally:
        try:
            if acquired:
                os.ftruncate(descriptor, 0)
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _validate_claim(value: object, *, index: int) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _CLAIM_FIELDS:
        raise RtlAssError(
            "invalid_verification_plan", "verification claim fields do not match the contract", {"index": index}
        )
    claim_id = value["id"]
    statement = value["statement"]
    kind = value["evidence_kind"]
    requirement = value["requirement"]
    expected = value["expected_status"]
    if not isinstance(claim_id, str) or not _IDENTIFIER.fullmatch(claim_id):
        raise RtlAssError("invalid_verification_plan", "verification claim identifier is invalid", {"index": index})
    if not isinstance(statement, str) or not 1 <= len(statement) <= 512:
        raise RtlAssError("invalid_verification_plan", "verification claim statement is invalid", {"index": index})
    if kind not in EVIDENCE_KINDS or requirement not in _REQUIREMENTS:
        raise RtlAssError(
            "invalid_verification_plan", "verification claim kind or requirement is invalid", {"index": index}
        )
    allowed_statuses = _WAVE_STATUSES if kind == "waveform" else frozenset({"pass"})
    if expected not in allowed_statuses:
        raise RtlAssError(
            "invalid_verification_plan", "verification claim expected status is invalid", {"index": index}
        )
    return dict(value)


def _validate_stop_policy(value: object) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != _STOP_POLICY_FIELDS:
        raise RtlAssError("invalid_verification_plan", "verification stop policy fields do not match the contract")
    retries = value["max_retries_per_claim"]
    parallel = value["max_parallel_eda"]
    if isinstance(retries, bool) or not isinstance(retries, int) or not 0 <= retries <= 3 or parallel != 1:
        raise RtlAssError("invalid_verification_plan", "verification stop policy values are invalid")
    return {"max_retries_per_claim": retries, "max_parallel_eda": 1}


def _parse_evidence_links(plan: VerificationPlan, links: Sequence[str]) -> dict[str, list[Path]]:
    parsed: dict[str, list[Path]] = {}
    known = plan.claims_by_id
    for index, link in enumerate(links):
        claim_id, separator, path_value = link.partition("=")
        if not separator or claim_id not in known or not path_value:
            raise RtlAssError(
                "invalid_evidence_link",
                "evidence links must use a known claim-id=path pair",
                {"index": index},
            )
        parsed.setdefault(claim_id, []).append(Path(path_value))
    return parsed


def _validate_claim_evidence(claim: Mapping[str, Any], path: Path) -> dict[str, Any]:
    source = _regular_input_file(path, label="claim evidence", max_bytes=_MAX_EVIDENCE_BYTES)
    try:
        value = parse_json(read_utf8_exact(source))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RtlAssError("invalid_claim_evidence", "claim evidence must be one UTF-8 JSON object") from exc
    if not isinstance(value, dict):
        raise RtlAssError("invalid_claim_evidence", "claim evidence root must be an object")
    if claim["evidence_kind"] == "waveform":
        normalized = validate_waveform_evidence(value, require_current_waveform=True)
        status = normalized["status"]
        input_hash = normalized["waveform_hash"]
        evidence_kind = "waveform"
    else:
        normalized = validate_run_evidence(
            value,
            require_current_artifacts=True,
            allowed_statuses=_RUN_STATUSES,
        )
        if normalized["kind"] != claim["evidence_kind"]:
            raise RtlAssError(
                "evidence_kind_mismatch",
                "linked evidence kind does not match its verification claim",
                {"claim_id": claim["id"], "expected": claim["evidence_kind"], "found": normalized["kind"]},
            )
        status = normalized["status"]
        input_hash = normalized["input_hash"]
        evidence_kind = normalized["kind"]
    return {
        "evidence_file": source.as_posix(),
        "evidence_file_hash": hash_file(source),
        "evidence_kind": evidence_kind,
        "input_hash": input_hash,
        "status": status,
    }


def _regular_input_file(path: str | Path, *, label: str, max_bytes: int) -> Path:
    source = Path(path)
    try:
        file_status = source.lstat()
    except OSError as exc:
        raise RtlAssError("input_not_found", f"{label} does not exist", {"path": str(path)}) from exc
    if not stat.S_ISREG(file_status.st_mode):
        raise RtlAssError("invalid_input_file", f"{label} must be a regular non-symlink file", {"path": str(path)})
    if file_status.st_size > max_bytes:
        raise RtlAssError("input_too_large", f"{label} exceeds the supported byte limit", {"max_bytes": max_bytes})
    return source


def _safe_directory(parent: Path, name: str) -> Path:
    path = parent / name
    with suppress(FileExistsError):
        path.mkdir(mode=0o700)
    try:
        path_status = path.lstat()
    except OSError as exc:
        raise RtlAssError("verification_lock_unavailable", "cannot inspect workspace lock directory") from exc
    if not stat.S_ISDIR(path_status.st_mode):
        raise RtlAssError("verification_lock_unavailable", "workspace lock path must be a real directory")
    return path
