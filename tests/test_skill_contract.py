from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from rtl_ass import __version__

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / ".agents" / "skills" / "rtl-ass"


def _string_constant(path: Path, name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for statement in tree.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if isinstance(target, ast.Name) and target.id == name and isinstance(statement.value, ast.Constant):
            value = statement.value.value
            if isinstance(value, str):
                return value
    raise AssertionError(f"missing string constant {name} in {path}")


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
        self.assertEqual(result.stdout.strip(), f"rtl-ass {__version__}")

    def test_release_version_is_consistent(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(__version__, "1.1.0")
        self.assertEqual(project["version"], __version__)
        self.assertEqual(_string_constant(ROOT / "tools" / "build_release_assets.py", "VERSION"), __version__)
        self.assertEqual(_string_constant(ROOT / "tools" / "release_audit.py", "RELEASE_VERSION"), __version__)

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
