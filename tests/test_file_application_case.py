from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from evals.file_application_case import CASE_ROOT, grade_packet_stage
from evals.run_codex_ab import _prepare_workspace, _workflow_audit
from evals.workflow_cases import get_case


@unittest.skipUnless(
    all(shutil.which(tool) for tool in ("iverilog", "vvp", "verilator")), "open grader tools unavailable"
)
class FileApplicationCaseTests(unittest.TestCase):
    def test_independent_reference_and_constraint_mutations(self) -> None:
        reference = (CASE_ROOT / "private" / "packet_tag_skid_reference.sv").read_text(encoding="utf-8")
        mutations = {
            "transform": ("in_data ^ MASK", "in_data"),
            "stability": ("default: begin end", "default: begin front <= beat; end"),
            "reset": ("count <= 0;", "count <= count;"),
            "registered-boundary": ("count < 2;", "count < 2 || out_ready;"),
            "throughput": ("count < 2;", "count == 0;"),
            "premature-finish": ("    reg [1:0] count;", "    initial $finish;\n    reg [1:0] count;"),
        }
        for name in ("reference", "delayed-ready", *mutations):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                workspace = root / "workspace"
                case = get_case("packet-tag-skid")
                initial = _prepare_workspace(workspace, "off", case)
                rtl = workspace / "rtl" / "packet_tag_skid.sv"
                rtl.parent.mkdir(exist_ok=True)
                text = reference
                if name == "delayed-ready":
                    text = text.replace(
                        "    reg [1:0] count;",
                        "    reg ready_enabled;\n    always @(posedge clk) ready_enabled <= rst_n;\n    reg [1:0] count;",
                    ).replace("count < 2;", "ready_enabled && count < 2;")
                if name in mutations:
                    before, after = mutations[name]
                    self.assertEqual(text.count(before), 1)
                    text = text.replace(before, after)
                rtl.write_text(text, encoding="utf-8")
                grade = grade_packet_stage(workspace, root / "grade", initial)
                self.assertEqual(grade["correct"], name in {"reference", "delayed-ready"}, grade["grader_statuses"])
                if name in {"transform", "stability", "reset", "registered-boundary", "throughput"}:
                    self.assertEqual(grade["application_constraints"][name]["status"], "fail")
                self.assertTrue(grade["protected_files_unchanged"])

    def test_usage_requirement_is_workflow_not_functional_correctness(self) -> None:
        case = get_case("packet-tag-skid")
        grade = {"correct": True, "protected_files_unchanged": True}
        missing = _workflow_audit({}, case, "off", grade)
        self.assertIn({"reason": "knowledge-use-declaration-missing-or-invalid"}, missing["violations"])
        empty = _workflow_audit({}, case, "off", grade, knowledge_application={"status": "audited", "uses": []})
        self.assertTrue(empty["compliant"])
        unsupported = _workflow_audit(
            {},
            case,
            "off",
            grade,
            knowledge_application={
                "status": "audited",
                "uses": [{"outcome": "unsupported"}],
            },
        )
        self.assertIn({"reason": "knowledge-use-claim-unsupported"}, unsupported["violations"])
        omitted = _workflow_audit(
            {},
            case,
            "off",
            grade,
            knowledge_application={
                "status": "audited",
                "uses": [],
                "unreported_read_ids": ["source"],
            },
        )
        self.assertIn({"reason": "knowledge-read-missing-use-declaration"}, omitted["violations"])


if __name__ == "__main__":
    unittest.main()
