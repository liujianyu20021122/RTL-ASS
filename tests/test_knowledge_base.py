from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rtl_ass.errors import RtlAssError
from rtl_ass.evidence import run_iverilog_simulation, run_verilator_lint
from rtl_ass.kb import (
    KnowledgeDatabase,
    KnowledgeRecordInput,
    LicenseStatus,
    ObservationAttribution,
    RecordRole,
    RecordStatus,
)
from rtl_ass.kb.gates import build_observation_set, build_verification_gate
from rtl_ass.kb.models import LinkRelation

RTL = "module counter(input logic clk); always_ff @(posedge clk) begin end endmodule\n"
TB = "module counter_tb; initial begin $finish; end endmodule\n"
FIXTURES = Path(__file__).parent / "fixtures"


class KnowledgeDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = KnowledgeDatabase(Path(self.tempdir.name) / "index.db")
        self.db.initialize(actor="test-suite")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _record(
        self,
        *,
        namespace: str = "project:one",
        role: RecordRole = RecordRole.RTL_DESIGN,
        content: str = RTL,
        source_path: str = "counter.sv",
    ) -> KnowledgeRecordInput:
        return KnowledgeRecordInput(
            namespace=namespace,
            role=role,
            language="systemverilog",
            title="counter",
            summary="verified-ready counter example",
            content=content,
            source_path=source_path,
            license_spdx="Apache-2.0",
            license_status=LicenseStatus.KNOWN,
        )

    def test_content_is_deduplicated_and_create_is_idempotent(self) -> None:
        first = self.db.add_record(self._record(), actor="test-suite")
        second = self.db.add_record(self._record(), actor="test-suite")
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["record"]["id"], second["record"]["id"])
        events = self.db.list_audit()
        self.assertEqual([event["action"] for event in events], ["record.create", "database.initialize"])

    def test_search_requires_explicit_namespace_and_is_isolated(self) -> None:
        self.db.add_record(self._record(namespace="project:one"), actor="test-suite")
        self.db.add_record(
            self._record(namespace="project:two", source_path="other.sv"),
            actor="test-suite",
        )
        results = self.db.search("counter", namespaces=["project:one"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["namespace"], "project:one")
        with self.assertRaises(RtlAssError):
            self.db.search("counter", namespaces=[])

    def test_verified_transition_requires_atomic_verification_workflow(self) -> None:
        record_id = self.db.add_record(self._record(), actor="test-suite")["record"]["id"]
        self.db.transition(record_id, RecordStatus.ANALYZED, actor="test-suite")
        self.db.transition(record_id, RecordStatus.CANDIDATE, actor="test-suite")
        with self.assertRaises(RtlAssError) as caught:
            self.db.transition(record_id, RecordStatus.VERIFIED, actor="test-suite")
        self.assertEqual(caught.exception.code, "verification_workflow_required")
        content_hash = hashlib.sha256(RTL.encode()).hexdigest()
        bundle_hash = hashlib.sha256(b"ordered DUT and TB bundle").hexdigest()
        evidence = self._gate_evidence(content_hash=content_hash, bundle_hash=bundle_hash)
        result = self.db.verify_record(
            record_id,
            evidence["evidence"],
            actor="test-suite",
        )
        self.assertEqual(result["record"]["status"], "verified")
        promoted = self.db.transition(record_id, RecordStatus.PROMOTED, actor="reviewer")
        self.assertEqual(promoted["status"], "promoted")

    def test_verified_transition_rejects_evidence_for_another_candidate(self) -> None:
        record_id = self.db.add_record(self._record(), actor="test-suite")["record"]["id"]
        self.db.transition(record_id, RecordStatus.ANALYZED, actor="test-suite")
        self.db.transition(record_id, RecordStatus.CANDIDATE, actor="test-suite")
        evidence = self._gate_evidence(
            content_hash=hashlib.sha256(b"another candidate").hexdigest(),
            bundle_hash=hashlib.sha256(b"another bundle").hexdigest(),
        )
        with self.assertRaises(RtlAssError) as caught:
            self.db.verify_record(
                record_id,
                evidence["evidence"],
                actor="test-suite",
            )
        self.assertEqual(caught.exception.code, "evidence_input_mismatch")

    def test_testbench_link_requires_compatible_roles(self) -> None:
        dut = self.db.add_record(self._record(), actor="test-suite")["record"]
        tb = self.db.add_record(
            self._record(role=RecordRole.TESTBENCH, content=TB, source_path="counter_tb.sv"),
            actor="test-suite",
        )["record"]
        link = self.db.add_link(tb["id"], dut["id"], LinkRelation.VERIFIES_DUT, actor="test-suite")
        self.assertEqual(link["relation"], "verifies-dut")
        with self.assertRaises(RtlAssError):
            self.db.add_link(dut["id"], tb["id"], LinkRelation.VERIFIES_DUT, actor="test-suite")

    @unittest.skipUnless(
        shutil.which("iverilog") and shutil.which("vvp") and shutil.which("verilator"),
        "Icarus Verilog or Verilator is unavailable",
    )
    def test_real_multitool_evidence_is_recorded_linked_and_verified_atomically(self) -> None:
        dut_path = FIXTURES / "counter.sv"
        record = self._record(content=dut_path.read_text(encoding="utf-8"), source_path="counter.sv")
        record_id = self.db.add_record(record, actor="test-suite")["record"]["id"]
        self.db.transition(record_id, RecordStatus.ANALYZED, actor="test-suite")
        self.db.transition(record_id, RecordStatus.CANDIDATE, actor="test-suite")
        artifacts = Path(self.tempdir.name) / "artifacts"
        run_evidence = [
            run_verilator_lint([dut_path], top="counter", artifact_root=artifacts),
            run_iverilog_simulation(
                [dut_path, FIXTURES / "counter_tb.sv"],
                top="counter_tb",
                artifact_root=artifacts,
            ),
        ]
        result = self.db.verify_record(
            record_id,
            run_evidence,
            actor="test-suite",
            required_evidence_kinds=("lint", "simulation"),
        )
        self.assertEqual(result["record"]["status"], "verified")
        self.assertEqual(result["gate"]["required_kinds"], ["lint", "simulation"])
        self.assertEqual(len(result["evidence_records"]), 2)
        self.assertEqual({record["role"] for record in result["evidence_records"]}, {"tool-evidence"})
        self.assertEqual({link["relation"] for link in result["links"]}, {"evidence-for"})
        self.assertEqual(len(self.db.list_links(record_id)), 2)
        self.assertTrue(self.db.verify_audit_chain()["valid"])

    def test_missing_required_kind_creates_no_partial_records(self) -> None:
        record_id = self.db.add_record(self._record(), actor="test-suite")["record"]["id"]
        self.db.transition(record_id, RecordStatus.ANALYZED, actor="test-suite")
        self.db.transition(record_id, RecordStatus.CANDIDATE, actor="test-suite")
        evidence_item = self._gate_evidence(
            content_hash=hashlib.sha256(RTL.encode()).hexdigest(),
            bundle_hash=hashlib.sha256(b"simulation bundle").hexdigest(),
        )["evidence"][0]
        before = self._database_counts()
        with self.assertRaises(RtlAssError) as caught:
            self.db.verify_record(
                record_id,
                [evidence_item],
                actor="test-suite",
                required_evidence_kinds=("lint", "simulation"),
            )
        self.assertEqual(caught.exception.code, "evidence_gate_unsatisfied")
        self.assertEqual(self._database_counts(), before)

    def test_transition_failure_rolls_back_evidence_records_links_and_audit(self) -> None:
        record_id = self.db.add_record(self._record(), actor="test-suite")["record"]["id"]
        self.db.transition(record_id, RecordStatus.ANALYZED, actor="test-suite")
        evidence_item = self._gate_evidence(
            content_hash=hashlib.sha256(RTL.encode()).hexdigest(),
            bundle_hash=hashlib.sha256(b"simulation bundle").hexdigest(),
        )["evidence"][0]
        before = self._database_counts()
        with self.assertRaises(RtlAssError) as caught:
            self.db.verify_record(
                record_id,
                [evidence_item],
                actor="test-suite",
                required_evidence_kinds=("simulation",),
            )
        self.assertEqual(caught.exception.code, "invalid_transition")
        self.assertEqual(self._database_counts(), before)

    @unittest.skipUnless(shutil.which("iverilog") and shutil.which("vvp"), "Icarus Verilog is unavailable")
    def test_changed_artifact_is_rejected_without_database_writes(self) -> None:
        dut_path = FIXTURES / "counter.sv"
        record = self._record(content=dut_path.read_text(encoding="utf-8"), source_path="counter.sv")
        record_id = self.db.add_record(record, actor="test-suite")["record"]["id"]
        self.db.transition(record_id, RecordStatus.ANALYZED, actor="test-suite")
        self.db.transition(record_id, RecordStatus.CANDIDATE, actor="test-suite")
        evidence = run_iverilog_simulation(
            [dut_path, FIXTURES / "counter_tb.sv"],
            top="counter_tb",
            artifact_root=Path(self.tempdir.name) / "artifacts",
        )
        Path(evidence["artifacts"][0]).write_text("tampered after the run\n", encoding="utf-8")
        before = self._database_counts()
        with self.assertRaises(RtlAssError) as caught:
            self.db.verify_record(
                record_id,
                [evidence],
                actor="test-suite",
                required_evidence_kinds=("simulation",),
            )
        self.assertEqual(caught.exception.code, "evidence_artifact_changed")
        self.assertEqual(self._database_counts(), before)

    def test_target_failure_is_retained_as_negative_evidence_without_status_change(self) -> None:
        record_id = self.db.add_record(self._record(), actor="test-suite")["record"]["id"]
        self.db.transition(record_id, RecordStatus.ANALYZED, actor="test-suite")
        self.db.transition(record_id, RecordStatus.CANDIDATE, actor="test-suite")
        evidence = self._observation_evidence(status="fail")
        before = self._database_counts()
        result = self.db.record_observations(
            record_id,
            [evidence],
            actor="reviewer",
            attribution=ObservationAttribution.TARGET,
        )
        self.assertEqual(result["record"]["status"], "candidate")
        self.assertEqual(result["attribution"], "target")
        self.assertEqual(result["links"][0]["relation"], "negative-for")
        self.assertEqual(result["evidence_records"][0]["verification"], {"run_status": "fail"})
        after = self._database_counts()
        self.assertEqual(after, (before[0] + 1, before[1] + 1, before[2] + 2))
        retry = self.db.record_observations(
            record_id,
            [evidence],
            actor="reviewer",
            attribution=ObservationAttribution.TARGET,
        )
        self.assertEqual(retry["links"], result["links"])
        self.assertEqual(self._database_counts(), after)
        with self.assertRaises(RtlAssError) as caught:
            self.db.record_observations(
                record_id,
                [evidence],
                actor="reviewer",
                attribution=ObservationAttribution.INFRASTRUCTURE,
            )
        self.assertEqual(caught.exception.code, "observation_attribution_conflict")
        self.assertEqual(self._database_counts(), after)

    def test_infrastructure_failure_is_not_mislabeled_as_target_negative(self) -> None:
        record_id = self.db.add_record(self._record(), actor="test-suite")["record"]["id"]
        result = self.db.record_observations(
            record_id,
            [self._observation_evidence(status="fail")],
            actor="reviewer",
            attribution=ObservationAttribution.INFRASTRUCTURE,
        )
        self.assertEqual(result["links"][0]["relation"], "evidence-for")
        self.assertEqual(result["links"][0]["source_record_id"], result["evidence_records"][0]["id"])
        stored_link = self.db.list_links(record_id)[0]
        self.assertEqual(stored_link["metadata"]["attribution"], "infrastructure")

    def test_timeout_cannot_be_attributed_to_target_and_writes_nothing(self) -> None:
        record_id = self.db.add_record(self._record(), actor="test-suite")["record"]["id"]
        before = self._database_counts()
        with self.assertRaises(RtlAssError) as caught:
            self.db.record_observations(
                record_id,
                [self._observation_evidence(status="timeout")],
                actor="reviewer",
                attribution=ObservationAttribution.TARGET,
            )
        self.assertEqual(caught.exception.code, "invalid_failure_attribution")
        self.assertEqual(self._database_counts(), before)

    def test_observation_artifact_change_rolls_back_without_evidence_record(self) -> None:
        record_id = self.db.add_record(self._record(), actor="test-suite")["record"]["id"]
        evidence = self._observation_evidence(status="fail")
        Path(evidence["artifacts"][0]).write_text("changed failure log\n", encoding="utf-8")
        before = self._database_counts()
        with self.assertRaises(RtlAssError) as caught:
            self.db.record_observations(
                record_id,
                [evidence],
                actor="reviewer",
                attribution=ObservationAttribution.TARGET,
            )
        self.assertEqual(caught.exception.code, "evidence_artifact_changed")
        self.assertEqual(self._database_counts(), before)

    def test_observation_subject_change_rolls_back_without_evidence_record(self) -> None:
        record_id = self.db.add_record(self._record(), actor="test-suite")["record"]["id"]
        evidence = self._observation_evidence(status="fail")
        Path(evidence["subject_hashes"][1]["path"]).write_text("changed testbench\n", encoding="utf-8")
        before = self._database_counts()
        with self.assertRaises(RtlAssError) as caught:
            self.db.record_observations(
                record_id,
                [evidence],
                actor="reviewer",
                attribution=ObservationAttribution.TARGET,
            )
        self.assertEqual(caught.exception.code, "evidence_subject_changed")
        self.assertEqual(self._database_counts(), before)

    def test_final_observation_recheck_failure_rolls_back_records_links_and_audit(self) -> None:
        record_id = self.db.add_record(self._record(), actor="test-suite")["record"]["id"]
        evidence = self._observation_evidence(status="fail")
        observation = build_observation_set(
            [evidence],
            content_hash=hashlib.sha256(RTL.encode()).hexdigest(),
            require_current_artifacts=True,
        )
        changed = {**observation, "observed_kinds": ["changed-after-insert"]}
        before = self._database_counts()
        with mock.patch(
            "rtl_ass.kb.database.build_observation_set",
            side_effect=[observation, changed],
        ):
            with self.assertRaises(RtlAssError) as caught:
                self.db.record_observations(
                    record_id,
                    [evidence],
                    actor="reviewer",
                    attribution=ObservationAttribution.TARGET,
                )
        self.assertEqual(caught.exception.code, "evidence_changed")
        self.assertEqual(self._database_counts(), before)

    def _gate_evidence(self, *, content_hash: str, bundle_hash: str) -> dict[str, object]:
        dut = Path(self.tempdir.name) / "counter.sv"
        testbench = Path(self.tempdir.name) / "counter_tb.sv"
        dut.write_text(RTL, encoding="utf-8")
        testbench.write_text(TB, encoding="utf-8")
        artifact = Path(self.tempdir.name) / f"{bundle_hash[:12]}.log"
        artifact.write_text("mock passing evidence\n", encoding="utf-8")
        evidence_file = Path(self.tempdir.name) / f"{bundle_hash[:12]}.json"
        item = {
            "schema_version": "1.0",
            "kind": "simulation",
            "status": "pass",
            "tool": {"name": "iverilog-vvp", "version": "test"},
            "input_hash": bundle_hash,
            "subject_hashes": [
                {"index": 0, "path": dut.as_posix(), "content_hash": content_hash},
                {
                    "index": 1,
                    "path": testbench.as_posix(),
                    "content_hash": hashlib.sha256(TB.encode()).hexdigest(),
                },
            ],
            "commands": [["iverilog", "counter.sv", "counter_tb.sv"], ["vvp", "simulation.vvp"]],
            "artifacts": [artifact.as_posix()],
            "artifact_hashes": [
                {
                    "index": 0,
                    "path": artifact.as_posix(),
                    "content_hash": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                }
            ],
            "claim_scope": "tool execution evidence only",
            "evidence_file": evidence_file.as_posix(),
            "started_at": "2026-08-31T00:00:00+00:00",
            "finished_at": "2026-08-31T00:00:01+00:00",
            "summary": {"returncode": 0},
        }
        evidence_file.write_text(json.dumps(item, sort_keys=True), encoding="utf-8")
        return build_verification_gate([item], content_hash=content_hash)

    def _observation_evidence(self, *, status: str) -> dict[str, object]:
        gate = self._gate_evidence(
            content_hash=hashlib.sha256(RTL.encode()).hexdigest(),
            bundle_hash=hashlib.sha256(f"{status} observation bundle".encode()).hexdigest(),
        )
        item = dict(gate["evidence"][0])
        item["status"] = status
        Path(item["evidence_file"]).write_text(json.dumps(item, sort_keys=True), encoding="utf-8")
        return item

    def _database_counts(self) -> tuple[int, int, int]:
        connection = sqlite3.connect(self.db.path)
        try:
            return tuple(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("records", "record_links", "audit_events")
            )
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
