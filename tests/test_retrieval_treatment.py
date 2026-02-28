from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from evals.retrieval_treatment import CONTAMINATION_REVIEW, validate_retrieval_treatment
from evals.run_codex_ab import _load_retrieval_treatment, _retrieval_case_identity
from evals.workflow_cases import get_case
from rtl_ass.errors import RtlAssError

ROOT = Path(__file__).resolve().parents[1]
RELEVANT = ROOT / "evals" / "retrieval_packs" / "signed-width" / "relevant-treatment.json"
IRRELEVANT = ROOT / "evals" / "retrieval_packs" / "signed-width" / "plausible-irrelevant-treatment.json"


class RetrievalTreatmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = get_case("systemverilog-signed-width")
        self.value = json.loads(RELEVANT.read_text(encoding="utf-8"))
        self.hashes = list(self.value["record_content_hashes"])

    def validate(self, value: object) -> dict[str, object]:
        return validate_retrieval_treatment(
            value,
            expected_case_identity=_retrieval_case_identity(self.case),
            calibrated_record_hashes=self.hashes,
        )

    def test_committed_relevant_treatment_binds_exact_case_and_cards(self) -> None:
        validated = self.validate(self.value)
        self.assertEqual(validated["treatment"], "relevant")
        self.assertEqual(validated["contamination_review"], CONTAMINATION_REVIEW)

    def test_committed_irrelevant_treatment_binds_exact_case_and_cards(self) -> None:
        value = json.loads(IRRELEVANT.read_text(encoding="utf-8"))
        validated = validate_retrieval_treatment(
            value,
            expected_case_identity=_retrieval_case_identity(self.case),
            calibrated_record_hashes=value["record_content_hashes"],
        )
        self.assertEqual(validated["treatment"], "plausible-irrelevant")
        self.assertTrue(validated["plausible_overlap"])
        self.assertTrue(validated["non_applicability_claims"])

    def test_treatment_rejects_case_or_record_identity_drift(self) -> None:
        wrong_case = copy.deepcopy(self.value)
        wrong_case["case_identity"]["prompt_hash"] = "0" * 64
        with self.assertRaises(RtlAssError) as case_error:
            self.validate(wrong_case)
        self.assertEqual(case_error.exception.code, "retrieval_treatment_case_mismatch")

        with self.assertRaises(RtlAssError) as record_error:
            validate_retrieval_treatment(
                self.value,
                expected_case_identity=_retrieval_case_identity(self.case),
                calibrated_record_hashes=["1" * 64],
            )
        self.assertEqual(record_error.exception.code, "retrieval_treatment_records_mismatch")

    def test_irrelevant_treatment_requires_overlap_and_non_applicability(self) -> None:
        irrelevant = copy.deepcopy(self.value)
        irrelevant["treatment"] = "plausible-irrelevant"
        irrelevant["applicability_claims"] = []
        irrelevant["plausible_overlap"] = ["width and valid terminology"]
        irrelevant["non_applicability_claims"] = ["The card concerns handshake storage, not arithmetic sizing."]
        self.assertEqual(self.validate(irrelevant)["treatment"], "plausible-irrelevant")

        irrelevant["non_applicability_claims"] = []
        with self.assertRaises(RtlAssError) as caught:
            self.validate(irrelevant)
        self.assertEqual(caught.exception.code, "invalid_retrieval_treatment")

    def test_lists_are_sorted_unique_and_review_time_has_offset(self) -> None:
        duplicate = copy.deepcopy(self.value)
        duplicate["decision_targets"] = ["signedness preservation", "signedness preservation"]
        with self.assertRaises(RtlAssError):
            self.validate(duplicate)

        local_time = copy.deepcopy(self.value)
        local_time["reviewed_at"] = "2026-09-04T00:00:00"
        with self.assertRaises(RtlAssError):
            self.validate(local_time)

    def test_loader_rejects_non_json_and_accepts_exact_database_audit(self) -> None:
        audit = {"record_content_hashes": self.hashes}
        loaded = _load_retrieval_treatment(RELEVANT, case=self.case, database_audit=audit)
        self.assertEqual(loaded, self.value)

        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "invalid.json"
            invalid.write_text("not json\n", encoding="utf-8")
            with self.assertRaises(RtlAssError) as caught:
                _load_retrieval_treatment(invalid, case=self.case, database_audit=audit)
        self.assertEqual(caught.exception.code, "invalid_retrieval_treatment")


if __name__ == "__main__":
    unittest.main()
