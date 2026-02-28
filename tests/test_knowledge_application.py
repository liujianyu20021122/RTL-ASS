from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from evals.knowledge_application import audit_application, validate_usage
from evals.run_codex_ab import _parse_trace
from rtl_ass.errors import RtlAssError
from rtl_ass.integrity import hash_bytes, hash_file


class KnowledgeApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "artifacts").mkdir()
        self.target = self.root / "design.sv"
        self.target.write_text("module design; endmodule\n", encoding="utf-8")
        self.usage: dict[str, Any] = {
            "schema_version": "1.0",
            "uses": [
                {
                    "record_id": "source",
                    "content_hash": "a" * 64,
                    "decision": "applied",
                    "reason": "preserve stalls",
                    "target": "design.sv",
                    "target_hash": hash_file(self.target),
                    "constraints": ["stability"],
                }
            ],
        }
        self.retrieval: dict[str, Any] = {
            "database_integrity": {"unchanged": True},
            "content_bound_read_ids": ["source"],
            "returned_records": [{"id": "source", "content_hash": "a" * 64, "status": "verified"}],
        }
        self.grade: dict[str, Any] = {
            "correct": True,
            "application_constraints": {
                "stability": {
                    "status": "pass",
                    "target": "design.sv",
                    "target_hash": hash_file(self.target),
                    "evidence_file_hash": "b" * 64,
                }
            },
        }

    def audit(self) -> dict[str, object]:
        (self.root / "artifacts" / "knowledge-use.json").write_text(json.dumps(self.usage), encoding="utf-8")
        return audit_application(self.root, self.retrieval, self.grade, {"decision_targets": ["stability"]})

    def test_supported_requires_declaration_identity_read_and_independent_constraint(self) -> None:
        self.assertEqual(audit_application(self.root, self.retrieval, self.grade)["status"], "not_reported")
        self.assertEqual(self.audit()["supported_application_count"], 1)
        self.assertEqual(self.audit()["causal_benefit"], "not_established")
        self.grade["application_constraints"] = {}
        self.assertEqual(self.audit()["supported_application_count"], 0)

    def test_forged_stale_raw_unread_and_failed_claims_do_not_pass(self) -> None:
        baseline = copy.deepcopy((self.usage, self.retrieval, self.grade))
        for defect in ("hash", "raw", "unread", "changed-db", "fail", "target", "unknown-constraint"):
            with self.subTest(defect=defect):
                self.usage, self.retrieval, self.grade = copy.deepcopy(baseline)
                if defect == "hash":
                    self.usage["uses"][0]["content_hash"] = "c" * 64
                elif defect == "raw":
                    self.retrieval["returned_records"][0]["status"] = "raw"
                elif defect == "unread":
                    self.retrieval["content_bound_read_ids"] = []
                elif defect == "changed-db":
                    self.retrieval["database_integrity"]["unchanged"] = False
                elif defect == "fail":
                    self.grade["application_constraints"]["stability"]["status"] = "fail"
                elif defect == "target":
                    self.usage["uses"][0]["target_hash"] = "d" * 64
                else:
                    self.usage["uses"][0]["constraints"] = ["unknown"]
                self.assertEqual(self.audit()["supported_application_count"], 0)

    def test_rejection_is_declaration_not_proof_of_correct_rejection(self) -> None:
        self.usage["uses"][0].update(decision="rejected", target=None, target_hash=None, constraints=[])
        self.retrieval["content_bound_read_ids"] = []
        self.assertEqual(self.audit()["declared_rejection_count"], 1)
        self.assertEqual(self.audit()["supported_application_count"], 0)

    def test_read_cannot_disappear_into_empty_declaration(self) -> None:
        self.usage["uses"] = []
        self.assertEqual(self.audit()["unreported_read_ids"], ["source"])

    def test_duplicate_unknown_fields_escape_and_symlink_are_rejected(self) -> None:
        duplicate = copy.deepcopy(self.usage)
        duplicate["uses"].append(copy.deepcopy(duplicate["uses"][0]))
        with self.assertRaises(RtlAssError):
            validate_usage(duplicate)
        for target in ("../design.sv", "/design.sv", "a/../design.sv", "a\\b.sv"):
            value = copy.deepcopy(self.usage)
            value["uses"][0]["target"] = target
            with self.assertRaises(RtlAssError):
                validate_usage(value)
        self.target.rename(self.root / "original.sv")
        self.target.symlink_to(self.root / "original.sv")
        self.assertEqual(self.audit()["supported_application_count"], 0)
        self.usage["uses"][0]["success"] = True
        self.assertEqual(self.audit()["status"], "invalid")

    def test_trace_requires_complete_hash_matching_content_output(self) -> None:
        content = "module example; endmodule\n"
        output = {"id": "source", "content": content, "content_hash": hash_bytes(content.encode())}
        for defect in ("none", "truncated", "wrong-hash", "wrong-id", "failed"):
            with self.subTest(defect=defect):
                value = dict(output)
                if defect == "wrong-hash":
                    value["content_hash"] = "0" * 64
                if defect == "wrong-id":
                    value["id"] = "other"
                event = {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "status": "completed",
                        "exit_code": int(defect == "failed"),
                        "command": "rtl-ass kb show source --include-content --db .rtl-ass/eval.db",
                        "aggregated_output": "{truncated" if defect == "truncated" else json.dumps(value),
                    },
                }
                trace = self.root / "trace.jsonl"
                trace.write_text(json.dumps(event) + "\n", encoding="utf-8")
                observation = _parse_trace(trace, self.root)
                self.assertEqual(len(observation["knowledge_reads"]), int(defect == "none"))
                self.assertNotIn(content, json.dumps(observation))


if __name__ == "__main__":
    unittest.main()
