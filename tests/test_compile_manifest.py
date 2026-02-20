from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rtl_ass.compile_manifest import CompileManifest
from rtl_ass.errors import RtlAssError


class CompileManifestTests(unittest.TestCase):
    def _project(self, root: Path) -> Path:
        (root / "rtl").mkdir(parents=True)
        (root / "lib").mkdir()
        (root / "include").mkdir()
        (root / "rtl" / "top.sv").write_text(
            "module top #(parameter WIDTH=1) (input logic a, output logic y); assign y = a; endmodule\n",
            encoding="utf-8",
        )
        (root / "lib" / "cell.v").write_text(
            "module cell(input a, output y); assign y=a; endmodule\n", encoding="utf-8"
        )
        (root / "include" / "defs.svh").write_text("`define DEFAULT_WIDTH 1\n", encoding="utf-8")
        (root / "include" / "NOTICE").write_text("tracked include-directory content\n", encoding="utf-8")
        manifest = {
            "schema_version": "1.0",
            "top": "top",
            "language": "systemverilog",
            "sources": ["rtl/top.sv"],
            "library_files": ["lib/cell.v"],
            "include_dirs": ["include"],
            "defines": {"FEATURE": None, "WIDTH": "8"},
            "parameters": {"WIDTH": "8"},
        }
        destination = root / "compile.json"
        destination.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
        return destination

    def test_manifest_binds_all_compile_inputs_and_is_path_independent(self) -> None:
        with tempfile.TemporaryDirectory() as first_directory, tempfile.TemporaryDirectory() as second_directory:
            first_root = Path(first_directory)
            second_root = Path(second_directory)
            first = CompileManifest.load(self._project(first_root))
            second = CompileManifest.load(self._project(second_root))

            self.assertEqual(first.input_hash, second.input_hash)
            self.assertEqual(first.summary()["tracked_input_count"], 5)
            self.assertEqual([item.text for item in first.defines], ["FEATURE", "WIDTH=8"])
            self.assertTrue(first.inputs_unchanged())
            (first_root / "include" / "defs.svh").write_text("`define DEFAULT_WIDTH 2\n", encoding="utf-8")
            self.assertFalse(first.inputs_unchanged())

            renamed = CompileManifest.load(self._project(first_root / "renamed"))
            include_file = first_root / "renamed" / "include" / "defs.svh"
            include_file.rename(include_file.with_name("renamed.svh"))
            self.assertFalse(renamed.inputs_unchanged())

    def test_manifest_rejects_path_escape_symlinks_and_option_injection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = self._project(root)
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
            value["sources"] = ["../outside.sv"]
            manifest_path.write_text(json.dumps(value) + "\n", encoding="utf-8")
            with self.assertRaises(RtlAssError) as caught:
                CompileManifest.load(manifest_path)
            self.assertEqual(caught.exception.code, "compile_manifest_path_escape")

            manifest_path = self._project(root / "second")
            (root / "second" / "include" / "link.svh").symlink_to(root / "second" / "include" / "defs.svh")
            with self.assertRaises(RtlAssError) as caught:
                CompileManifest.load(manifest_path)
            self.assertEqual(caught.exception.code, "include_symlink_not_allowed")

            manifest_path = self._project(root / "third")
            source = root / "third" / "rtl" / "top.sv"
            linked_source = source.with_name("linked.sv")
            linked_source.symlink_to(source)
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
            value["sources"] = ["rtl/linked.sv"]
            manifest_path.write_text(json.dumps(value) + "\n", encoding="utf-8")
            with self.assertRaises(RtlAssError) as caught:
                CompileManifest.load(manifest_path)
            self.assertEqual(caught.exception.code, "compile_manifest_symlink_not_allowed")

            value["sources"] = [""]
            manifest_path.write_text(json.dumps(value) + "\n", encoding="utf-8")
            with self.assertRaises(RtlAssError) as caught:
                CompileManifest.load(manifest_path)
            self.assertEqual(caught.exception.code, "invalid_compile_manifest")

            with self.assertRaises(RtlAssError) as caught:
                CompileManifest.create([root / "rtl" / "top.sv"], "top", defines=["BAD=x;write_json=pwned"])
            self.assertEqual(caught.exception.code, "invalid_compile_option")

    def test_inline_contract_rejects_duplicate_names_and_language_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            verilog = root / "top.v"
            systemverilog = root / "top.sv"
            verilog.write_text("module top; endmodule\n", encoding="utf-8")
            systemverilog.write_text("module top; endmodule\n", encoding="utf-8")
            with self.assertRaises(RtlAssError) as caught:
                CompileManifest.create([verilog], "top", parameters=["WIDTH=8", "WIDTH=16"])
            self.assertEqual(caught.exception.code, "duplicate_compile_option")
            with self.assertRaises(RtlAssError) as caught:
                CompileManifest.create([systemverilog], "top", language="verilog-2005")
            self.assertEqual(caught.exception.code, "language_source_mismatch")

    def test_manifest_and_compile_option_resource_limits_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "compile.json"
            manifest.write_text(" " * (1024 * 1024 + 1), encoding="utf-8")
            with self.assertRaises(RtlAssError) as caught:
                CompileManifest.load(manifest)
            self.assertEqual(caught.exception.code, "compile_manifest_too_large")

            source = root / "top.sv"
            source.write_text("module top; endmodule\n", encoding="utf-8")
            with self.assertRaises(RtlAssError) as caught:
                CompileManifest.create([source], "top", defines=[f"D{index}" for index in range(4097)])
            self.assertEqual(caught.exception.code, "too_many_compile_options")

            first_include = root / "first-include"
            second_include = root / "second-include"
            first_include.mkdir()
            second_include.mkdir()
            (first_include / "first.svh").write_text("// first\n", encoding="utf-8")
            (second_include / "second.svh").write_text("// second\n", encoding="utf-8")
            with mock.patch("rtl_ass.compile_manifest.MAX_INCLUDE_FILES", 1):
                with self.assertRaises(RtlAssError) as caught:
                    CompileManifest.create([source], "top", include_dirs=[first_include, second_include])
            self.assertEqual(caught.exception.code, "include_snapshot_too_large")


if __name__ == "__main__":
    unittest.main()
