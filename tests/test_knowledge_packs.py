from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from rtl_ass.errors import RtlAssError
from rtl_ass.integrity import hash_bytes
from rtl_ass.kb import KnowledgeDatabase, KnowledgeRecordInput, LicenseStatus, RecordRole
from rtl_ass.kb.models import LinkRelation
from rtl_ass.kb.packs import knowledge_pack_hash, load_knowledge_pack, write_knowledge_pack

SOURCE = "module skid(input logic valid); endmodule\n"
DERIVED = "Keep ready/valid payload stable while valid is asserted and ready is deasserted.\n"


class KnowledgePackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = KnowledgeDatabase(self.root / "knowledge.db")
        self.db.initialize(actor="test-suite")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _source(self, *, license_status: LicenseStatus = LicenseStatus.KNOWN) -> dict[str, Any]:
        result = self.db.add_record(
            KnowledgeRecordInput(
                namespace="project:source",
                role=RecordRole.RTL_DESIGN,
                language="systemverilog",
                title="skid buffer",
                summary="source RTL",
                content=SOURCE,
                source_uri="https://example.invalid/skid",
                source_revision="deadbeef",
                source_path="rtl/skid.sv",
                license_spdx="Apache-2.0" if license_status is LicenseStatus.KNOWN else "UNKNOWN",
                license_status=license_status,
            ),
            actor="test-suite",
        )
        return cast(dict[str, Any], result["record"])

    def test_derivation_is_candidate_provenanced_and_idempotent(self) -> None:
        source = self._source()
        arguments: dict[str, Any] = {
            "namespace": "project:distilled",
            "role": RecordRole.DESIGN_PATTERN,
            "language": "markdown",
            "title": "ready valid stability",
            "summary": "distilled handshake invariant",
            "content": DERIVED,
            "source_path": "cards/ready-valid.md",
            "method": "generalize",
            "actor": "curator",
        }
        first = self.db.derive_record(str(source["id"]), **arguments)
        audit_count = len(self.db.list_audit())
        second = self.db.derive_record(str(source["id"]), **arguments)
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(len(self.db.list_audit()), audit_count)
        self.assertEqual(first["record"]["status"], "candidate")
        self.assertEqual(first["record"]["license_spdx"], "Apache-2.0")
        self.assertEqual(first["record"]["metadata"]["derivation"]["source_content_hash"], source["content_hash"])
        self.assertEqual(first["link"]["relation"], "derived-from")
        self.assertTrue(self.db.verify_audit_chain()["valid"])

    def test_derivation_rejects_tool_evidence_as_source_or_output(self) -> None:
        source = self._source()
        common = {
            "namespace": "project:distilled",
            "language": "markdown",
            "title": "pattern",
            "summary": "summary",
            "content": DERIVED,
            "source_path": "pattern.md",
            "method": "extract",
            "actor": "curator",
        }
        with self.assertRaises(RtlAssError) as caught:
            self.db.derive_record(str(source["id"]), role=RecordRole.TOOL_EVIDENCE, **common)
        self.assertEqual(caught.exception.code, "invalid_derivation_role")

        evidence = self.db.add_record(
            KnowledgeRecordInput(
                namespace="project:evidence",
                role=RecordRole.TOOL_EVIDENCE,
                language="json",
                title="lint evidence",
                summary="tool output",
                content='{"status":"pass"}',
                license_spdx="N/A",
                license_status=LicenseStatus.NOT_APPLICABLE,
            ),
            actor="test-suite",
        )["record"]
        with self.assertRaises(RtlAssError) as caught:
            self.db.derive_record(str(evidence["id"]), role=RecordRole.VERIFICATION_PATTERN, **common)
        self.assertEqual(caught.exception.code, "invalid_derivation_source")

    def test_export_import_round_trip_is_atomic_and_audited(self) -> None:
        source = self._source()
        derived = self.db.derive_record(
            str(source["id"]),
            namespace="project:source",
            role=RecordRole.DESIGN_PATTERN,
            language="markdown",
            title="ready valid stability",
            summary="distilled handshake invariant",
            content=DERIVED,
            source_path="cards/ready-valid.md",
            method="generalize",
            actor="curator",
        )["record"]
        pack = self.db.export_pack(
            [str(source["id"]), str(derived["id"])],
            name="round-trip",
            version="1.0.0",
            description="portable pack test",
            license_spdx="Apache-2.0",
        )
        pack_path = write_knowledge_pack(pack, self.root / "pack.json")
        loaded = load_knowledge_pack(pack_path)
        self.assertEqual(loaded["pack_hash"], pack["pack_hash"])
        imported = self.db.import_pack(pack_path, namespace="pack:round-trip", actor="importer")
        audit_count = len(self.db.list_audit())
        repeated = self.db.import_pack(pack_path, namespace="pack:round-trip", actor="importer")
        self.assertEqual(imported["created_count"], 2)
        self.assertEqual(repeated["created_count"], 0)
        self.assertEqual(len(self.db.list_audit()), audit_count)
        self.assertEqual({item["status"] for item in imported["records"]}, {"raw"})
        self.assertEqual(imported["links"][0]["relation"], LinkRelation.DERIVED_FROM.value)
        self.assertTrue(self.db.verify_audit_chain()["valid"])

    def test_conflicting_immutable_fields_are_not_silently_deduplicated(self) -> None:
        self._source()
        before = len(self.db.list_audit())
        conflicting = KnowledgeRecordInput(
            namespace="project:source",
            role=RecordRole.RTL_DESIGN,
            language="systemverilog",
            title="changed title",
            summary="source RTL",
            content=SOURCE,
            source_uri="https://example.invalid/skid",
            source_revision="deadbeef",
            source_path="rtl/skid.sv",
            license_spdx="MIT",
            license_status=LicenseStatus.KNOWN,
        )
        with self.assertRaises(RtlAssError) as caught:
            self.db.add_record(conflicting, actor="test-suite")
        self.assertEqual(caught.exception.code, "record_identity_conflict")
        self.assertEqual(len(self.db.list_audit()), before)

    def test_tampered_content_and_path_escape_are_rejected_before_writes(self) -> None:
        content_path = self.root / "content.md"
        content_path.write_text(DERIVED, encoding="utf-8")
        record = {
            "key": "pattern",
            "role": "design-pattern",
            "language": "markdown",
            "title": "pattern",
            "summary": "summary",
            "content_hash": hash_bytes(DERIVED.encode("utf-8")),
            "source_uri": "",
            "source_revision": "",
            "source_path": "content.md",
            "license_spdx": "Apache-2.0",
            "license_status": "known",
            "metadata": {},
            "content_path": "content.md",
        }
        pack = {
            "schema_version": "1.0",
            "name": "strict-pack",
            "version": "1.0.0",
            "description": "strict validation",
            "license_spdx": "Apache-2.0",
            "records": [record],
            "links": [],
        }
        pack["pack_hash"] = knowledge_pack_hash(pack)
        path = self.root / "strict.json"
        path.write_text(json.dumps(pack), encoding="utf-8")
        content_path.write_text("tampered\n", encoding="utf-8")
        before = len(self.db.list_audit())
        with self.assertRaises(RtlAssError) as caught:
            self.db.import_pack(path, namespace="pack:strict", actor="importer")
        self.assertEqual(caught.exception.code, "pack_content_hash_mismatch")
        self.assertEqual(len(self.db.list_audit()), before)

        record["content_path"] = "../outside.md"
        pack["pack_hash"] = knowledge_pack_hash(pack)
        path.write_text(json.dumps(pack), encoding="utf-8")
        with self.assertRaises(RtlAssError) as caught:
            load_knowledge_pack(path)
        self.assertEqual(caught.exception.code, "pack_path_escape")

    def test_non_redistribution_license_status_cannot_be_exported(self) -> None:
        for status in (LicenseStatus.UNKNOWN, LicenseStatus.INCOMPATIBLE, LicenseStatus.NOT_APPLICABLE):
            with self.subTest(status=status):
                record = self.db.add_record(
                    KnowledgeRecordInput(
                        namespace=f"project:{status.value}",
                        role=RecordRole.DESIGN_PATTERN,
                        language="markdown",
                        title="local pattern",
                        summary="not cleared for redistribution",
                        content=f"local content for {status.value}\n",
                        license_spdx="UNKNOWN",
                        license_status=status,
                    ),
                    actor="test-suite",
                )["record"]
                with self.assertRaises(RtlAssError) as caught:
                    self.db.export_pack(
                        [str(record["id"])],
                        name="blocked",
                        version="1.0.0",
                        description="must not export",
                        license_spdx="UNKNOWN",
                    )
                self.assertEqual(caught.exception.code, "pack_license_blocked")


if __name__ == "__main__":
    unittest.main()
