from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from rtl_ass.evidence_drivers import run_eqy_equivalence, run_symbiyosys_formal

FIXTURES = Path(__file__).parent / "fixtures"


class FormalDriverTests(unittest.TestCase):
    def _run_fake_eqy(self, artifact_root: Path) -> dict[str, Any]:
        return run_eqy_equivalence(
            reference_sources=[FIXTURES / "equiv_reference.sv"],
            implementation_sources=[FIXTURES / "equiv_implementation.sv"],
            reference_top="equiv_reference",
            implementation_top="equiv_implementation",
            depth=1,
            artifact_root=artifact_root,
        )

    def _fake_drivers(self, root: Path) -> Path:
        binary = root / "bin"
        binary.mkdir()
        program = """#!/usr/bin/python3
import os
import sys
from pathlib import Path

name = Path(sys.argv[0]).name
if "--version" in sys.argv:
    print(f"{name} fake-1.0")
    raise SystemExit(0)
output = Path(sys.argv[sys.argv.index("-d") + 1])
output.mkdir(parents=True)
status = os.environ.get("RTL_ASS_FAKE_STATUS", "PASS")
if status != "MISSING":
    if name == "sby":
        (output / "status").write_text(status + "\\n", encoding="utf-8")
    else:
        (output / status).write_text("\\n", encoding="utf-8")
        (output / "logfile.txt").write_text(status + "\\n", encoding="utf-8")
if os.environ.get("RTL_ASS_FAKE_TRACE") == "1":
    trace = output / "engine_0" / "trace.vcd"
    trace.parent.mkdir(parents=True)
    trace.write_text("$date fake $end\\n$enddefinitions $end\\n", encoding="utf-8")
raise SystemExit(2 if name == "eqy" and status == "FAIL" else 0)
"""
        for name in ("sby", "eqy"):
            path = binary / name
            path.write_text(program, encoding="utf-8")
            path.chmod(0o755)
        return binary

    def test_sby_requires_a_driver_marker_and_counterexample_for_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = self._fake_drivers(root)
            environment = {"PATH": f"{binary}:{os.environ['PATH']}"}
            with mock.patch.dict(os.environ, {**environment, "RTL_ASS_FAKE_STATUS": "PASS"}):
                passing = run_symbiyosys_formal(
                    [FIXTURES / "formal_pass.sv"],
                    top="formal_pass",
                    depth=4,
                    initialization="defined",
                    artifact_root=root / "pass",
                )
            with mock.patch.dict(os.environ, {**environment, "RTL_ASS_FAKE_STATUS": "FAIL"}):
                unsubstantiated = run_symbiyosys_formal(
                    [FIXTURES / "formal_fail.sv"],
                    top="formal_fail",
                    depth=4,
                    initialization="zero",
                    artifact_root=root / "blocked",
                )
            with mock.patch.dict(os.environ, {**environment, "RTL_ASS_FAKE_STATUS": "MISSING"}):
                missing = run_symbiyosys_formal(
                    [FIXTURES / "formal_pass.sv"],
                    top="formal_pass",
                    depth=4,
                    initialization="defined",
                    artifact_root=root / "missing",
                )
            with mock.patch.dict(
                os.environ,
                {**environment, "RTL_ASS_FAKE_STATUS": "FAIL", "RTL_ASS_FAKE_TRACE": "1"},
            ):
                failing = run_symbiyosys_formal(
                    [FIXTURES / "formal_fail.sv"],
                    top="formal_fail",
                    depth=4,
                    initialization="zero",
                    artifact_root=root / "fail",
                )
            config = next(Path(path) for path in passing["artifacts"] if Path(path).suffix == ".sby")
            config_content = config.read_text(encoding="utf-8")

        self.assertEqual(passing["status"], "pass")
        self.assertEqual(unsubstantiated["status"], "blocked")
        self.assertEqual(missing["status"], "blocked")
        self.assertEqual(failing["status"], "fail")
        self.assertIn("mode bmc\ndepth 4", config_content)

    def test_eqy_failure_is_negative_only_with_a_counterexample(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = self._fake_drivers(root)
            environment = {"PATH": f"{binary}:{os.environ['PATH']}"}
            with mock.patch.dict(os.environ, {**environment, "RTL_ASS_FAKE_STATUS": "PASS"}):
                passing = self._run_fake_eqy(root / "pass")
            with mock.patch.dict(os.environ, {**environment, "RTL_ASS_FAKE_STATUS": "FAIL"}):
                unsubstantiated = self._run_fake_eqy(root / "blocked")
            with mock.patch.dict(os.environ, {**environment, "RTL_ASS_FAKE_STATUS": "MISSING"}):
                missing = self._run_fake_eqy(root / "missing")
            with mock.patch.dict(
                os.environ,
                {**environment, "RTL_ASS_FAKE_STATUS": "FAIL", "RTL_ASS_FAKE_TRACE": "1"},
            ):
                failing = self._run_fake_eqy(root / "fail")
            config = next(Path(path) for path in passing["artifacts"] if Path(path).suffix == ".eqy")
            config_content = config.read_text(encoding="utf-8")

        self.assertEqual(passing["status"], "pass")
        self.assertEqual(unsubstantiated["status"], "blocked")
        self.assertEqual(missing["status"], "blocked")
        self.assertEqual(failing["status"], "fail")
        self.assertIn("[gold]", config_content)
        self.assertIn("[gate]", config_content)
        self.assertIn("use sby", config_content)

    @unittest.skipUnless(
        all(shutil.which(tool) for tool in ("sby", "eqy", "yosys", "yosys-smtbmc", "z3")),
        "SymbiYosys, EQY, Yosys, and Z3 are required for the native-driver gate",
    )
    def test_real_drivers_distinguish_positive_and_negative_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal_pass = run_symbiyosys_formal(
                [FIXTURES / "formal_pass.sv"],
                top="formal_pass",
                depth=4,
                initialization="defined",
                artifact_root=root / "formal-pass",
            )
            formal_fail = run_symbiyosys_formal(
                [FIXTURES / "formal_fail.sv"],
                top="formal_fail",
                depth=4,
                initialization="defined",
                artifact_root=root / "formal-fail",
            )
            equivalence_pass = run_eqy_equivalence(
                reference_sources=[FIXTURES / "equiv_reference.sv"],
                implementation_sources=[FIXTURES / "equiv_implementation.sv"],
                reference_top="equiv_reference",
                implementation_top="equiv_implementation",
                depth=1,
                artifact_root=root / "equivalence-pass",
            )
            equivalence_fail = run_eqy_equivalence(
                reference_sources=[FIXTURES / "equiv_reference.sv"],
                implementation_sources=[FIXTURES / "equiv_mismatch.sv"],
                reference_top="equiv_reference",
                implementation_top="equiv_mismatch",
                depth=1,
                artifact_root=root / "equivalence-fail",
            )

        self.assertEqual(formal_pass["status"], "pass", formal_pass["summary"])
        self.assertEqual(formal_fail["status"], "fail", formal_fail["summary"])
        self.assertGreater(formal_fail["summary"]["counterexample_count"], 0)
        self.assertEqual(equivalence_pass["status"], "pass", equivalence_pass["summary"])
        self.assertEqual(equivalence_fail["status"], "fail", equivalence_fail["summary"])
        self.assertGreater(equivalence_fail["summary"]["counterexample_count"], 0)


if __name__ == "__main__":
    unittest.main()
