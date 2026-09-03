from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
FORMAL_REQUIREMENTS = ROOT / ".github" / "formal-requirements.txt"


class CiContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_every_ci_job_has_a_wall_clock_limit(self) -> None:
        self.assertEqual(self.workflow.count("    timeout-minutes:"), 3)
        self.assertIn("  test:\n    runs-on: ubuntu-24.04\n    timeout-minutes: 45", self.workflow)
        self.assertIn("  opensta-gate:\n    runs-on: ubuntu-24.04\n    timeout-minutes: 45", self.workflow)
        self.assertIn("  formal-drivers-gate:\n    runs-on: ubuntu-24.04\n    timeout-minutes: 60", self.workflow)

    def test_opensta_build_binds_the_validated_flex_header_directory(self) -> None:
        self.assertIn("test -f /usr/include/FlexLexer.h", self.workflow)
        self.assertIn("-DFLEX_INCLUDE_DIR=/usr/include", self.workflow)

    def test_formal_python_runtime_is_complete_and_hash_locked(self) -> None:
        requirements = FORMAL_REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        self.assertEqual({line.split("==", 1)[0] for line in requirements}, {"click", "z3-solver"})
        for requirement in requirements:
            self.assertRegex(requirement, r"^[a-z0-9-]+==[^ ]+ --hash=sha256:[0-9a-f]{64}$")
        self.assertIn("--require-hashes --no-deps --target build/formal-install", self.workflow)


if __name__ == "__main__":
    unittest.main()
