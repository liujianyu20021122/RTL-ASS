from __future__ import annotations

import hashlib
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from evals.soc_workflow_cases import (
    CORE_V_MCU_EVENT_IRQ,
    SocSourceSpec,
    _extract_regular_archive,
    _materialize_source,
)
from rtl_ass.integrity import hash_file


class SocEvaluationTests(unittest.TestCase):
    def test_core_v_mcu_case_uses_full_pinned_identities(self) -> None:
        spec = CORE_V_MCU_EVENT_IRQ
        self.assertEqual(len(spec.base_revision), 40)
        self.assertEqual(len(spec.hidden_revision), 40)
        self.assertEqual(len(spec.base_tree), 40)
        for digest in (spec.affected_source_hash, spec.mutated_source_hash, spec.hidden_hash):
            self.assertEqual(len(digest), 64)
            int(digest, 16)
        self.assertNotEqual(spec.affected_source_hash, spec.mutated_source_hash)

    def test_archive_extractor_rejects_links(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "unsafe.tar"
            with tarfile.open(archive, "w") as handle:
                member = tarfile.TarInfo("unsafe-link")
                member.type = tarfile.SYMTYPE
                member.linkname = "/etc/passwd"
                handle.addfile(member)

            with self.assertRaises(ValueError):
                _extract_regular_archive(archive, root / "output")

    def test_materializer_binds_git_tree_mutation_and_hidden_test(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository, spec = self._synthetic_repository(root)
            mutated = f"module dut;\n{spec.mutation_after}\nendmodule\n".encode()

            destination = root / "materialized"
            provenance = _materialize_source(spec, repository, destination)

            self.assertEqual((destination / "public" / "rtl" / "dut.sv").read_bytes(), mutated)
            self.assertEqual(hash_file(destination / "private" / "soc_event_generator_hidden_tb.sv"), spec.hidden_hash)
            self.assertEqual(provenance["base_revision"], spec.base_revision)
            self.assertTrue(provenance["canonical_origin_observed"])
            self.assertFalse((destination / "public" / "tb").exists())
            with self.assertRaises(FileExistsError):
                _materialize_source(spec, repository, destination)

    def _synthetic_repository(self, root: Path) -> tuple[Path, SocSourceSpec]:
        repository = root / "source"
        repository.mkdir()
        self._git(repository, "init", "-b", "main")
        self._git(repository, "config", "user.name", "SoC Eval Test")
        self._git(repository, "config", "user.email", "soc-eval@example.invalid")
        self._git(repository, "remote", "add", "origin", "https://example.invalid/soc.git")
        affected = repository / "rtl" / "dut.sv"
        affected.parent.mkdir()
        before = "  assign pop = ack && (ack_id == 11);"
        after = "  assign pop = ack;"
        affected.write_text(f"module dut;\n{before}\nendmodule\n", encoding="utf-8")
        self._git(repository, "add", ".")
        self._git(repository, "commit", "-m", "base")
        base_revision = self._git(repository, "rev-parse", "HEAD").strip()
        base_tree = self._git(repository, "show", "-s", "--format=%T", "HEAD").strip()
        affected_hash = hash_file(affected)
        hidden = repository / "tb" / "hidden.sv"
        hidden.parent.mkdir()
        hidden.write_text("module hidden; endmodule\n", encoding="utf-8")
        self._git(repository, "add", ".")
        self._git(repository, "commit", "-m", "hidden")
        return repository, SocSourceSpec(
            identifier="synthetic-soc-case",
            repository_url="https://example.invalid/soc.git",
            base_revision=base_revision,
            base_tree=base_tree,
            source_file_count=1,
            affected_path="rtl/dut.sv",
            affected_source_hash=affected_hash,
            mutated_source_hash=hashlib.sha256(f"module dut;\n{after}\nendmodule\n".encode()).hexdigest(),
            mutation_before=before,
            mutation_after=after,
            hidden_revision=self._git(repository, "rev-parse", "HEAD").strip(),
            hidden_path="tb/hidden.sv",
            hidden_hash=hash_file(hidden),
            source_license="test-only",
            hidden_license="test-only",
        )

    @staticmethod
    def _git(repository: Path, *arguments: str) -> str:
        result = subprocess.run(
            ["git", "-C", repository.as_posix(), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout


if __name__ == "__main__":
    unittest.main()
