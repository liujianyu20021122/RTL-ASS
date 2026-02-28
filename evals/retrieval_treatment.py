"""Strict, task-bound treatment manifests for retrieval-effect evaluations."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from rtl_ass.errors import RtlAssError

CONTAMINATION_REVIEW = "no-task-source-no-test-no-reference-no-patch-no-grader-output"
TREATMENTS = frozenset({"relevant", "plausible-irrelevant"})
_FIELDS = frozenset(
    {
        "schema_version",
        "case_identity",
        "treatment",
        "record_content_hashes",
        "query_concepts",
        "decision_targets",
        "plausible_overlap",
        "applicability_claims",
        "non_applicability_claims",
        "contamination_review",
        "reviewer",
        "reviewed_at",
    }
)
_CASE_IDENTITY_FIELDS = frozenset({"case_id", "prompt_hash", "fixture_hash", "hidden_grader_hash"})


def validate_retrieval_treatment(
    value: object,
    *,
    expected_case_identity: Mapping[str, str],
    calibrated_record_hashes: Sequence[str],
) -> dict[str, Any]:
    """Validate that a human relevance judgment binds the exact task and card set."""
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise RtlAssError("invalid_retrieval_treatment", "retrieval treatment fields do not match the contract")
    treatment = value["treatment"]
    if value["schema_version"] != "1.0" or not isinstance(treatment, str) or treatment not in TREATMENTS:
        raise RtlAssError("invalid_retrieval_treatment", "retrieval treatment version or label is invalid")

    case_identity = value["case_identity"]
    if (
        not isinstance(case_identity, dict)
        or set(case_identity) != _CASE_IDENTITY_FIELDS
        or dict(case_identity) != dict(expected_case_identity)
    ):
        raise RtlAssError(
            "retrieval_treatment_case_mismatch",
            "retrieval treatment does not bind the exact evaluated case",
        )

    record_hashes = _hash_list(value["record_content_hashes"], "record_content_hashes", minimum=1, maximum=3)
    expected_hashes = sorted(set(calibrated_record_hashes))
    if record_hashes != expected_hashes or len(expected_hashes) != len(calibrated_record_hashes):
        raise RtlAssError(
            "retrieval_treatment_records_mismatch",
            "retrieval treatment does not bind the exact calibrated card set",
        )

    _text_list(value["query_concepts"], "query_concepts", minimum=1, maximum=12)
    _text_list(value["decision_targets"], "decision_targets", minimum=1, maximum=12)
    overlap = _text_list(value["plausible_overlap"], "plausible_overlap", minimum=0, maximum=12)
    applicable = _text_list(value["applicability_claims"], "applicability_claims", minimum=0, maximum=12)
    non_applicable = _text_list(value["non_applicability_claims"], "non_applicability_claims", minimum=0, maximum=12)
    if treatment == "relevant" and not applicable:
        raise RtlAssError(
            "invalid_retrieval_treatment",
            "a relevant treatment requires at least one task-specific applicability claim",
        )
    if treatment == "plausible-irrelevant" and (not overlap or not non_applicable):
        raise RtlAssError(
            "invalid_retrieval_treatment",
            "a plausible-irrelevant treatment requires both lexical overlap and non-applicability claims",
        )
    if value["contamination_review"] != CONTAMINATION_REVIEW:
        raise RtlAssError(
            "invalid_retrieval_treatment",
            "retrieval treatment is missing the exact semantic contamination review",
        )
    if not isinstance(value["reviewer"], str) or not value["reviewer"].strip() or len(value["reviewer"]) > 128:
        raise RtlAssError("invalid_retrieval_treatment", "retrieval treatment reviewer is invalid")
    reviewed_at = value["reviewed_at"]
    if not isinstance(reviewed_at, str):
        raise RtlAssError("invalid_retrieval_treatment", "retrieval treatment review time is invalid")
    try:
        parsed = datetime.fromisoformat(reviewed_at)
    except ValueError as exc:
        raise RtlAssError("invalid_retrieval_treatment", "retrieval treatment review time is invalid") from exc
    if parsed.tzinfo is None:
        raise RtlAssError("invalid_retrieval_treatment", "retrieval treatment review time requires a UTC offset")
    return dict(value)


def _hash_list(value: object, field: str, *, minimum: int, maximum: int) -> list[str]:
    items = _text_list(value, field, minimum=minimum, maximum=maximum)
    if any(len(item) != 64 or any(character not in "0123456789abcdef" for character in item) for item in items):
        raise RtlAssError("invalid_retrieval_treatment", f"{field} must contain lowercase SHA-256 values")
    return items


def _text_list(value: object, field: str, *, minimum: int, maximum: int) -> list[str]:
    if (
        not isinstance(value, list)
        or not minimum <= len(value) <= maximum
        or any(not isinstance(item, str) or not item.strip() or len(item) > 512 for item in value)
        or value != sorted(set(value))
    ):
        raise RtlAssError(
            "invalid_retrieval_treatment",
            f"{field} must contain {minimum}-{maximum} sorted unique bounded strings",
        )
    return list(value)
