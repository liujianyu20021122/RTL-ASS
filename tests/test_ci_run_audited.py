from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "tools" / "ci_run_audited.sh"


class CiRunAuditedTests(unittest.TestCase):
    def test_success_preserves_output_and_exit_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "success.log"
            result = subprocess.run(
                [str(WRAPPER), "success", str(log_path), "printf", "clean output\n"],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0)
            self.assertEqual(log_path.read_text(encoding="utf-8"), "clean output\n")
            self.assertNotIn("::error", result.stdout)

    def test_failure_emits_bounded_escaped_annotation_and_original_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "failure.log"
            result = subprocess.run(
                [
                    str(WRAPPER),
                    "failing: check, exact",
                    str(log_path),
                    "bash",
                    "-c",
                    "printf 'first line\\nsecond %% line\\n'; exit 23",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 23)
            self.assertEqual(log_path.read_text(encoding="utf-8"), "first line\nsecond % line\n")
            self.assertIn(
                "::error title=failing%3A check%2C exact::exit=23%0Afirst line%0Asecond %25 line",
                result.stdout,
            )

    def test_failure_annotation_is_bounded_to_the_log_tail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "bounded.log"
            result = subprocess.run(
                [
                    str(WRAPPER),
                    "bounded",
                    str(log_path),
                    "bash",
                    "-c",
                    "printf 'prefix-'; head -c 20000 /dev/zero | tr '\\0' x; printf '%s\\n' '-suffix'; exit 1",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            annotation = result.stdout.splitlines()[-1]
            self.assertEqual(result.returncode, 1)
            self.assertLessEqual(len(annotation), 8064)
            self.assertNotIn("prefix-", annotation)
            self.assertIn("-suffix", annotation)


if __name__ == "__main__":
    unittest.main()
