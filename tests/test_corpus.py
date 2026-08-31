from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rtl_ass.corpus import audit_corpus, write_manifest_atomic

MIT_LICENSE = """MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy.
"""


class CorpusAuditTests(unittest.TestCase):
    def test_non_git_source_stays_quarantined_and_counts_rtl_tb(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "upstream"
            source = root / "example"
            source.mkdir(parents=True)
            (source / "LICENSE").write_text(MIT_LICENSE, encoding="utf-8")
            (source / "design.sv").write_text("module design; endmodule\n", encoding="utf-8")
            tests = source / "tests"
            tests.mkdir()
            (tests / "design_tb.sv").write_text("module design_tb; endmodule\n", encoding="utf-8")

            manifest = audit_corpus(root)
            audited = manifest["sources"][0]
            self.assertEqual(audited["trust_status"], "quarantine")
            self.assertFalse(audited["reproducibly_pinned"])
            self.assertEqual(audited["license_finding"]["spdx_candidate"], "MIT")
            self.assertEqual(audited["counts"]["systemverilog_files"], 2)
            self.assertEqual(audited["counts"]["testbench_candidates"], 1)
            self.assertFalse(audited["trusted_retrieval_eligible"])
            self.assertEqual(audited["benchmark_contamination_risk"], "not_detected")

    def test_manifest_write_is_complete_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "upstream"
            (root / "empty").mkdir(parents=True)
            manifest = audit_corpus(root)
            destination = write_manifest_atomic(manifest, Path(directory) / "manifest.json")
            self.assertTrue(destination.read_text(encoding="utf-8").endswith("\n"))
            self.assertFalse(destination.with_name(".manifest.json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
