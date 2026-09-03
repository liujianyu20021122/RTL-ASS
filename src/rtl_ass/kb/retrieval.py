"""Immutable receipts for bounded, explicit-namespace knowledge retrieval."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from rtl_ass.errors import RtlAssError
from rtl_ass.integrity import canonical_json, hash_json
from rtl_ass.kb.models import LicenseStatus, RecordRole, RecordStatus, validate_identifier

_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "actor",
        "query",
        "namespaces",
        "limit",
        "filters",
        "result_count",
        "results",
        "retrieval_hash",
    }
)
_RESULT_FIELDS = frozenset(
    {
        "index",
        "id",
        "namespace",
        "role",
        "status",
        "language",
        "title",
        "summary",
        "content_hash",
        "source_uri",
        "source_revision",
        "source_path",
        "license_spdx",
        "license_status",
        "metadata",
        "verification",
        "excerpt",
        "rank",
    }
)
_HASH_FIELDS = ("retrieval_hash",)
_ROLE_VALUES = frozenset(role.value for role in RecordRole)
_STATUS_VALUES = frozenset(status.value for status in RecordStatus)
_LICENSE_STATUS_VALUES = frozenset(status.value for status in LicenseStatus)


def build_retrieval_receipt(
    results: Sequence[Mapping[str, Any]],
    *,
    actor: str,
    query: str,
    namespaces: Sequence[str],
    limit: int,
    role: str | None,
    status: str | None,
    match_mode: str,
) -> dict[str, Any]:
    validate_identifier(actor, "actor")
    if not isinstance(query, str) or not query.strip():
        raise RtlAssError("empty_search", "retrieval receipt requires the exact non-empty search query")
    namespace_values = tuple(sorted(set(namespaces)))
    if not namespace_values or len(namespace_values) != len(namespaces) or len(namespace_values) > 16:
        raise RtlAssError("invalid_retrieval", "retrieval namespaces must be 1-16 unique identifiers")
    for namespace in namespace_values:
        validate_identifier(namespace, "namespace")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50 or len(results) > limit:
        raise RtlAssError("invalid_retrieval", "retrieval limit or result count is invalid")
    if match_mode not in {"all", "any"}:
        raise RtlAssError("invalid_retrieval", "retrieval match mode must be 'all' or 'any'")
    cards = [_result_card(result, index=index, namespaces=namespace_values) for index, result in enumerate(results)]
    receipt = {
        "schema_version": "1.0",
        "kind": "knowledge-retrieval",
        "actor": actor,
        "query": query,
        "namespaces": list(namespace_values),
        "limit": limit,
        "filters": {"role": role, "status": status, "match_mode": match_mode},
        "result_count": len(cards),
        "results": cards,
    }
    return {**receipt, "retrieval_hash": hash_json(receipt)}


def validate_retrieval_receipt(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _RECEIPT_FIELDS:
        raise RtlAssError("invalid_retrieval_receipt", "retrieval receipt fields do not match the contract")
    try:
        canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise RtlAssError("invalid_retrieval_receipt", "retrieval receipt must contain finite JSON values") from exc
    actor = value["actor"]
    query = value["query"]
    namespaces = value["namespaces"]
    limit = value["limit"]
    filters = value["filters"]
    results = value["results"]
    if (
        value["schema_version"] != "1.0"
        or value["kind"] != "knowledge-retrieval"
        or not isinstance(actor, str)
        or not isinstance(query, str)
        or not query.strip()
        or not isinstance(namespaces, list)
        or not all(isinstance(namespace, str) for namespace in namespaces)
        or namespaces != sorted(set(namespaces))
        or not 1 <= len(namespaces) <= 16
        or isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= 50
        or not isinstance(filters, dict)
        or set(filters) != {"role", "status", "match_mode"}
        or filters["role"] not in _ROLE_VALUES | {None}
        or filters["status"] not in _STATUS_VALUES | {None}
        or filters["match_mode"] not in {"all", "any"}
        or not isinstance(results, list)
        or len(results) > limit
        or value["result_count"] != len(results)
    ):
        raise RtlAssError("invalid_retrieval_receipt", "retrieval receipt values do not match the contract")
    validate_identifier(actor, "actor")
    for namespace in namespaces:
        validate_identifier(namespace, "namespace")
    normalized_results = [_validate_result_card(result, index, namespaces) for index, result in enumerate(results)]
    if len({result["id"] for result in normalized_results}) != len(normalized_results):
        raise RtlAssError("invalid_retrieval_receipt", "retrieval receipt contains duplicate record identifiers")
    payload = {field: value[field] for field in _RECEIPT_FIELDS if field not in _HASH_FIELDS}
    if value["retrieval_hash"] != hash_json(payload):
        raise RtlAssError("retrieval_hash_mismatch", "retrieval receipt hash does not match its query and results")
    return dict(value)


def write_retrieval_receipt(value: Mapping[str, Any], path: str | Path) -> Path:
    receipt = validate_retrieval_receipt(dict(value))
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and (destination.is_symlink() or not destination.is_file()):
        raise RtlAssError("invalid_retrieval_output", "retrieval output must be a regular non-symlink file")
    temporary = destination.with_name(f".{destination.name}.tmp")
    if temporary.exists() and (temporary.is_symlink() or not temporary.is_file()):
        raise RtlAssError("invalid_retrieval_output", "retrieval temporary path is unsafe")
    try:
        temporary.write_text(canonical_json(receipt) + "\n", encoding="utf-8")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def _result_card(value: Mapping[str, Any], *, index: int, namespaces: Sequence[str]) -> dict[str, Any]:
    missing = sorted((_RESULT_FIELDS - {"index"}).difference(value))
    if missing:
        raise RtlAssError(
            "invalid_retrieval", "search result is missing receipt fields", {"index": index, "missing": missing}
        )
    card = {field: value[field] for field in _RESULT_FIELDS if field != "index"}
    card["index"] = index
    return _validate_result_card(card, index, namespaces)


def _validate_result_card(value: object, index: int, namespaces: Sequence[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _RESULT_FIELDS or value.get("index") != index:
        raise RtlAssError("invalid_retrieval_receipt", "retrieval result fields or index are invalid", {"index": index})
    string_fields = _RESULT_FIELDS - {"index", "metadata", "verification", "rank"}
    if (
        any(not isinstance(value[field], str) for field in string_fields)
        or not all(value[field] for field in ("id", "namespace", "role", "status", "language", "title"))
        or value["namespace"] not in namespaces
        or value["role"] not in _ROLE_VALUES
        or value["status"] not in _STATUS_VALUES
        or value["license_status"] not in _LICENSE_STATUS_VALUES
        or not value["license_spdx"]
        or len(value["content_hash"]) != 64
        or any(character not in "0123456789abcdef" for character in value["content_hash"])
        or not isinstance(value["metadata"], dict)
        or not isinstance(value["verification"], dict)
        or isinstance(value["rank"], bool)
        or not isinstance(value["rank"], (int, float))
    ):
        raise RtlAssError("invalid_retrieval_receipt", "retrieval result values are invalid", {"index": index})
    validate_identifier(value["id"], "result.id")
    return dict(value)
