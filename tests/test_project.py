from __future__ import annotations

import unittest
from pathlib import Path

from rtl_ass.project import inspect_project, strip_comments

FIXTURES = Path(__file__).parent / "fixtures"


class ProjectInspectionTests(unittest.TestCase):
    def test_inspects_systemverilog_design_and_testbench_separately(self) -> None:
        report = inspect_project(FIXTURES)
        self.assertGreaterEqual(report["file_count"], 2)
        files = {item["path"]: item for item in report["files"]}
        self.assertEqual(files["counter.sv"]["role"], "rtl-design")
        self.assertEqual(files["counter_tb.sv"]["role"], "testbench")
        self.assertEqual(files["counter.sv"]["modules"], ["counter"])
        self.assertIn("clk", files["counter.sv"]["clock_hints"])
        self.assertIn("rst_n", files["counter.sv"]["reset_hints"])
        self.assertIn("lexical hints", report["limitations"][0])

    def test_comment_stripping_preserves_string_and_line_count(self) -> None:
        source = 'module x; // module fake\ninitial $display("// not a comment"); /* block\ncomment */ endmodule\n'
        stripped = strip_comments(source)
        self.assertNotIn("module fake", stripped)
        self.assertIn('"// not a comment"', stripped)
        self.assertEqual(source.count("\n"), stripped.count("\n"))


if __name__ == "__main__":
    unittest.main()
