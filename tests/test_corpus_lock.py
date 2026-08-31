from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from rtl_ass.cli import main
from rtl_ass.corpus_lock import build_corpus_lock, import_corpus_lock, load_corpus_lock, write_corpus_lock
from rtl_ass.errors import RtlAssError
from rtl_ass.integrity import hash_file, hash_json
from rtl_ass.kb.database import KnowledgeDatabase
from rtl_ass.kb.models import KnowledgeRecordInput, RecordRole

MIT_LICENSE = """MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy.
THE SOFTWARE IS PROVIDED "AS IS".
"""


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


class CorpusLockTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, Path]:
        corpus = root / "corpus"
        source_root = root / "research" / "upstream"
        repository = source_root / "example"
        (repository / "rtl").mkdir(parents=True)
        (repository / "tb").mkdir()
        (repository / "LICENSE").write_text(MIT_LICENSE, encoding="utf-8")
        (repository / "rtl" / "design.sv").write_text(
            "module design(input logic clk, output logic q); always_ff @(posedge clk) q <= ~q; endmodule\n",
            encoding="utf-8",
        )
        (repository / "tb" / "design_tb.sv").write_text(
            'module design_tb; initial begin $display("ok"); $finish; end endmodule\n',
            encoding="utf-8",
        )
        _git(repository, "init", "-b", "main")
        _git(repository, "config", "user.name", "Test")
        _git(repository, "config", "user.email", "test@example.com")
        _git(repository, "remote", "add", "origin", "https://example.invalid/example.git")
        _git(repository, "add", ".")
        _git(repository, "commit", "-m", "fixture")
        revision = _git(repository, "rev-parse", "HEAD")

        corpus.mkdir()
        upstream = {
            "schema_version": "1.0",
            "generated_at": "2026-08-31T00:00:00+00:00",
            "source_root": "research/upstream",
            "source_count": 2,
            "sources": [
                {
                    "name": "example",
                    "source_kind": "git",
                    "source_uri": "https://example.invalid/example.git",
                    "revision": revision,
                    "reproducibly_pinned": True,
                    "source_identity": "a" * 64,
                    "benchmark_contamination_risk": "not_detected",
                    "license_finding": {
                        "status": "detected",
                        "spdx_candidate": "MIT",
                        "path": "LICENSE",
                        "content_hash": hash_file(repository / "LICENSE"),
                    },
                },
                {"name": "excluded"},
            ],
            "policy": {},
        }
        (corpus / "upstream.json").write_text(json.dumps(upstream), encoding="utf-8")
        policy = {
            "schema_version": "1.0",
            "lock_created_at": "2026-08-31T00:00:00+00:00",
            "upstream_manifest": "corpus/upstream.json",
            "source_root": "research/upstream",
            "limits": {"max_files": 10, "max_total_bytes": 10000, "max_source_bytes": 5000},
            "sources": [
                {
                    "name": "example",
                    "decision": "include",
                    "rationale": "Pinned test repository with a reviewed license.",
                    "namespace": "corpus:example",
                    "license_review": {
                        "spdx": "MIT",
                        "license_path": "LICENSE",
                        "license_hash": hash_file(repository / "LICENSE"),
                        "reviewed_by": "test-suite",
                        "reviewed_at": "2026-08-31",
                        "scope": "local-index-no-redistribution",
                    },
                    "selections": [
                        {"kind": "prefix", "path": "rtl/", "role": "design-auto"},
                        {"kind": "prefix", "path": "tb/", "role": "testbench"},
                    ],
                },
                {"name": "excluded", "decision": "exclude", "rationale": "Not selected for this fixture."},
            ],
        }
        policy_path = corpus / "policy.json"
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        return policy_path, source_root, repository

    def test_cli_lock_import_and_statistics_form_one_machine_readable_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy_path, source_root, _ = self._fixture(root)
            lock_path = root / "corpus" / "lock.json"
            database_path = root / "index.db"
            commands = [
                [
                    "corpus",
                    "lock",
                    str(policy_path),
                    "--source-root",
                    str(source_root),
                    "--output",
                    str(lock_path),
                ],
                ["kb", "init", "--db", str(database_path), "--actor", "test-suite"],
                [
                    "kb",
                    "import-corpus",
                    str(lock_path),
                    "--source-root",
                    str(source_root),
                    "--db",
                    str(database_path),
                    "--actor",
                    "test-suite",
                ],
                ["kb", "stats", "--db", str(database_path)],
            ]
            payloads: list[dict[str, object]] = []
            for command in commands:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    status = main(command)
                self.assertEqual(status, 0, output.getvalue())
                payloads.append(json.loads(output.getvalue()))
            self.assertEqual(payloads[0]["file_count"], 2)
            self.assertEqual(payloads[2]["created_count"], 2)
            self.assertEqual(payloads[3]["records"], 2)
            self.assertEqual(payloads[3]["by_language"], {"systemverilog": 2})

    def test_lock_and_atomic_import_are_idempotent_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy_path, source_root, _ = self._fixture(root)
            lock = build_corpus_lock(policy_path)
            self.assertEqual(lock, build_corpus_lock(policy_path))
            lock_path = write_corpus_lock(lock, root / "corpus" / "lock.json")
            loaded = load_corpus_lock(lock_path)
            self.assertEqual(loaded["file_count"], 2)
            self.assertEqual(loaded["repositories"][0]["files"][0]["role"], "rtl-design")

            database = KnowledgeDatabase(root / "index.db")
            database.initialize(actor="test-suite")
            imported = import_corpus_lock(
                database,
                lock_path,
                source_root=source_root,
                actor="test-suite",
            )
            repeated = import_corpus_lock(
                database,
                lock_path,
                source_root=source_root,
                actor="test-suite",
            )
            self.assertEqual(imported["created_count"], 2)
            self.assertEqual(repeated["created_count"], 0)
            self.assertEqual(repeated["repeated_count"], 2)
            self.assertTrue(repeated["audit_chain"]["valid"])
            self.assertEqual(len(database.search("design", namespaces=["corpus:example"], limit=10)), 2)
            statistics = database.statistics()
            self.assertEqual(statistics["records"], 2)
            self.assertEqual(statistics["by_role"], {"rtl-design": 1, "testbench": 1})
            self.assertEqual(statistics["by_namespace"], {"corpus:example": 2})
            self.assertTrue(statistics["audit_chain"]["valid"])

    def test_changed_checkout_and_tampered_lock_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy_path, source_root, repository = self._fixture(root)
            lock = build_corpus_lock(policy_path)
            lock_path = write_corpus_lock(lock, root / "corpus" / "lock.json")

            tampered = json.loads(lock_path.read_text(encoding="utf-8"))
            tampered["file_count"] = 1
            lock_path.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaises(RtlAssError) as caught:
                load_corpus_lock(lock_path)
            self.assertEqual(caught.exception.code, "corpus_lock_hash_mismatch")

            malformed = dict(lock)
            malformed["repositories"][0]["files"][0]["content_hash"] = "not-a-sha256"
            malformed.pop("lock_hash")
            malformed["lock_hash"] = hash_json(malformed)
            lock_path.write_text(json.dumps(malformed), encoding="utf-8")
            with self.assertRaises(RtlAssError) as caught:
                load_corpus_lock(lock_path)
            self.assertEqual(caught.exception.code, "invalid_corpus_hash")

            noncanonical = json.loads(json.dumps(lock))
            noncanonical["repositories"][0]["files"][0]["path"] = "rtl//design.sv"
            noncanonical.pop("lock_hash")
            noncanonical["lock_hash"] = hash_json(noncanonical)
            lock_path.write_text(json.dumps(noncanonical), encoding="utf-8")
            with self.assertRaises(RtlAssError) as caught:
                load_corpus_lock(lock_path)
            self.assertEqual(caught.exception.code, "invalid_corpus_path")

            invalid_date = json.loads(json.dumps(lock))
            invalid_date["generated_at"] = "2026-08-31"
            invalid_date.pop("lock_hash")
            invalid_date["lock_hash"] = hash_json(invalid_date)
            lock_path.write_text(json.dumps(invalid_date), encoding="utf-8")
            with self.assertRaises(RtlAssError) as caught:
                load_corpus_lock(lock_path)
            self.assertEqual(caught.exception.code, "invalid_corpus_date")

            nested_repository = json.loads(json.dumps(lock))
            nested_repository["repositories"][0]["name"] = "nested/example"
            nested_repository.pop("lock_hash")
            nested_repository["lock_hash"] = hash_json(nested_repository)
            lock_path.write_text(json.dumps(nested_repository), encoding="utf-8")
            with self.assertRaises(RtlAssError) as caught:
                load_corpus_lock(lock_path)
            self.assertEqual(caught.exception.code, "invalid_corpus_repository_name")

            (repository / "rtl" / "design.sv").write_text("module changed; endmodule\n", encoding="utf-8")
            with self.assertRaises(RtlAssError) as caught:
                build_corpus_lock(policy_path, source_root=source_root)
            self.assertEqual(caught.exception.code, "corpus_repository_mismatch")

    def test_untracked_license_file_cannot_authorize_a_pinned_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy_path, _, repository = self._fixture(root)
            untracked_license = repository / "UNTRACKED_LICENSE"
            untracked_license.write_text(MIT_LICENSE, encoding="utf-8")
            license_hash = hash_file(untracked_license)

            upstream_path = root / "corpus" / "upstream.json"
            upstream = json.loads(upstream_path.read_text(encoding="utf-8"))
            upstream["sources"][0]["license_finding"].update(
                {"path": "UNTRACKED_LICENSE", "content_hash": license_hash}
            )
            upstream_path.write_text(json.dumps(upstream), encoding="utf-8")
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            policy["sources"][0]["license_review"].update(
                {"license_path": "UNTRACKED_LICENSE", "license_hash": license_hash}
            )
            policy_path.write_text(json.dumps(policy), encoding="utf-8")

            with self.assertRaises(RtlAssError) as caught:
                build_corpus_lock(policy_path)
            self.assertEqual(caught.exception.code, "corpus_license_untracked")

    def test_add_records_rolls_back_the_complete_batch_on_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = KnowledgeDatabase(Path(directory) / "index.db")
            database.initialize(actor="test-suite")
            existing = KnowledgeRecordInput(
                namespace="corpus:batch",
                role=RecordRole.RTL_DESIGN,
                language="systemverilog",
                title="Existing",
                summary="Existing record",
                content="module existing; endmodule\n",
                source_path="existing.sv",
            )
            database.add_record(existing, actor="test-suite")
            new_record = KnowledgeRecordInput(
                namespace="corpus:batch",
                role=RecordRole.RTL_DESIGN,
                language="systemverilog",
                title="New",
                summary="New record",
                content="module new_record; endmodule\n",
                source_path="new.sv",
            )
            conflicting = KnowledgeRecordInput(
                namespace=existing.namespace,
                role=existing.role,
                language=existing.language,
                title="Changed immutable title",
                summary=existing.summary,
                content=existing.content,
                source_path=existing.source_path,
            )
            with self.assertRaises(RtlAssError) as caught:
                database.add_records([new_record, conflicting], actor="test-suite")
            self.assertEqual(caught.exception.code, "record_identity_conflict")
            with self.assertRaises(RtlAssError):
                database.get_record(new_record.identity)


if __name__ == "__main__":
    unittest.main()
