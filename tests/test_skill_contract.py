from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / ".agents" / "skills" / "rtl-ass"


class SkillContractTests(unittest.TestCase):
    def test_standalone_launcher_does_not_shadow_installed_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory) / "rtl-ass"
            shutil.copytree(SKILL_ROOT, skill)
            environment = {"PYTHONPATH": str(ROOT / "src")}
            result = subprocess.run(
                [sys.executable, str(skill / "scripts" / "rtl_ass.py"), "--version"],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "rtl-ass 1.0.0")

    def test_frontmatter_and_progressive_references_are_complete(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(skill.startswith("---\n"))
        frontmatter = skill.split("---", 2)[1]
        self.assertRegex(frontmatter, r"(?m)^name: rtl-ass$")
        self.assertRegex(frontmatter, r"(?m)^description: \S.+$")
        self.assertNotIn("TODO", skill)
        reference_paths = re.findall(r"\]\((references/[^)]+\.md)\)", skill)
        self.assertGreaterEqual(len(reference_paths), 6)
        for relative_path in reference_paths:
            self.assertTrue((SKILL_ROOT / relative_path).is_file(), relative_path)

    def test_openai_metadata_invokes_the_exact_skill_name(self) -> None:
        metadata = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("$rtl-ass", metadata)
        self.assertIn("allow_implicit_invocation: true", metadata)


if __name__ == "__main__":
    unittest.main()
