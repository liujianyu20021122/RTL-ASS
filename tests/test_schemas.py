from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from referencing import Registry, Resource

from rtl_ass.evidence import run_iverilog_simulation, run_yosys_equivalence, run_yosys_formal
from rtl_ass.kb.database import KnowledgeDatabase
from rtl_ass.kb.gates import build_observation_set, build_verification_gate
from rtl_ass.kb.packs import knowledge_pack_hash, validate_knowledge_pack
from rtl_ass.kb.retrieval import build_retrieval_receipt
from rtl_ass.waveform import query_waveform
from rtl_ass.workflow import validate_verification_plan

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
SCHEMAS = {path.name: json.loads(path.read_text(encoding="utf-8")) for path in (ROOT / "schemas").glob("*.json")}
REGISTRY = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in SCHEMAS.values())


def validate_instance(schema: dict[str, object], instance: object) -> None:
    Draft202012Validator(schema, registry=REGISTRY).validate(instance)


class SchemaContractTests(unittest.TestCase):
    def test_retrieval_receipt_matches_declared_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = KnowledgeDatabase(Path(directory) / "index.db")
            database.initialize(actor="test-suite")
            database.import_pack(
                ROOT / "library" / "starter" / "pack.json",
                namespace="builtin:starter",
                actor="test-suite",
            )
            receipt = build_retrieval_receipt(
                database.search("ready", namespaces=["builtin:starter"], limit=2),
                actor="codex",
                query="ready",
                namespaces=["builtin:starter"],
                limit=2,
                role=None,
                status=None,
                match_mode="all",
            )
        validate_instance(SCHEMAS["retrieval-receipt.schema.json"], receipt)
        self.assertEqual(receipt["result_count"], len(receipt["results"]))

    def test_verification_plan_matches_declared_contract(self) -> None:
        plan = {
            "schema_version": "1.0",
            "plan_id": "schema-contract",
            "task_class": "debugging",
            "claims": [
                {
                    "id": "regression",
                    "statement": "The supplied regression passes.",
                    "evidence_kind": "simulation",
                    "requirement": "required",
                    "expected_status": "pass",
                },
                {
                    "id": "divergence",
                    "statement": "The first relevant divergence is present.",
                    "evidence_kind": "waveform",
                    "requirement": "optional",
                    "expected_status": "found",
                },
            ],
            "stop_policy": {"max_retries_per_claim": 1, "max_parallel_eda": 1},
        }
        validated = validate_verification_plan(plan)
        validate_instance(SCHEMAS["verification-plan.schema.json"], validated.value)
        self.assertEqual(len(validated.plan_hash), 64)

    def test_knowledge_statistics_match_declared_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = KnowledgeDatabase(Path(directory) / "index.db")
            database.initialize(actor="test-suite")
            statistics = database.statistics()
        validate_instance(SCHEMAS["knowledge-stats.schema.json"], statistics)
        self.assertEqual(statistics["records"], 0)
        self.assertTrue(statistics["audit_chain"]["valid"])

    def test_curated_corpus_policy_and_lock_match_declared_contracts(self) -> None:
        policy = json.loads((ROOT / "corpus" / "ingestion-policy.json").read_text(encoding="utf-8"))
        lock = json.loads((ROOT / "corpus" / "curated-lock.json").read_text(encoding="utf-8"))
        validate_instance(SCHEMAS["corpus-policy.schema.json"], policy)
        validate_instance(SCHEMAS["corpus-lock.schema.json"], lock)
        self.assertEqual(len(policy["sources"]), 21)
        self.assertEqual(lock["repository_count"], 7)
        self.assertEqual(lock["file_count"], sum(len(repository["files"]) for repository in lock["repositories"]))

    def test_knowledge_pack_matches_declared_schema_contract(self) -> None:
        schema = json.loads((ROOT / "schemas" / "knowledge-pack.schema.json").read_text(encoding="utf-8"))
        content = "A bounded ready/valid verification pattern.\n"
        pack = {
            "schema_version": "1.0",
            "name": "schema-fixture",
            "version": "1.0.0",
            "description": "schema contract fixture",
            "license_spdx": "Apache-2.0",
            "records": [
                {
                    "key": "pattern",
                    "role": "verification-pattern",
                    "language": "markdown",
                    "title": "ready valid",
                    "summary": "bounded pattern",
                    "content_hash": __import__("hashlib").sha256(content.encode()).hexdigest(),
                    "source_uri": "",
                    "source_revision": "",
                    "source_path": "pattern.md",
                    "license_spdx": "Apache-2.0",
                    "license_status": "known",
                    "metadata": {},
                    "content": content,
                }
            ],
            "links": [],
        }
        pack["pack_hash"] = knowledge_pack_hash(pack)
        validated = validate_knowledge_pack(pack)
        validate_instance(schema, validated)
        self.assertEqual(set(validated), set(schema["required"]))
        self.assertEqual(validated["schema_version"], schema["properties"]["schema_version"]["const"])

    @unittest.skipUnless(shutil.which("vcd2fst") and shutil.which("fst2vcd"), "GTKWave FST converters are unavailable")
    def test_fst_query_matches_waveform_schema_contract(self) -> None:
        schema = json.loads((ROOT / "schemas" / "wave-query.schema.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            fst_path = Path(directory) / "divergence.fst"
            result = shutil.which("vcd2fst")
            if result is None:
                self.fail("vcd2fst disappeared after the availability check")
            conversion = subprocess.run(
                [result, str(FIXTURES / "divergence.vcd"), str(fst_path)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(conversion.returncode, 0)
            query = query_waveform(fst_path, patterns=("tb.actual",))
        validate_instance(schema, query)
        self.assertTrue(set(schema["required"]).issubset(query))
        self.assertTrue(set(query).issubset(schema["properties"]))
        self.assertIn(query["kind"], schema["properties"]["kind"]["enum"])

    @unittest.skipUnless(shutil.which("yosys"), "Yosys is unavailable")
    def test_formal_and_equivalence_evidence_match_run_contract(self) -> None:
        schema = json.loads((ROOT / "schemas" / "run-evidence.schema.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            evidence_items = [
                run_yosys_formal(
                    [FIXTURES / "formal_pass.sv"],
                    top="formal_pass",
                    depth=3,
                    initialization="defined",
                    artifact_root=directory,
                ),
                run_yosys_equivalence(
                    reference_sources=[FIXTURES / "equiv_reference.sv"],
                    implementation_sources=[FIXTURES / "equiv_implementation.sv"],
                    reference_top="equiv_reference",
                    implementation_top="equiv_implementation",
                    depth=1,
                    artifact_root=directory,
                ),
            ]
        for evidence in evidence_items:
            with self.subTest(kind=evidence["kind"]):
                validate_instance(schema, evidence)
                self.assertTrue(set(schema["required"]).issubset(evidence))
                self.assertTrue(set(evidence).issubset(schema["properties"]))
                self.assertIn(evidence["kind"], schema["properties"]["kind"]["enum"])

    @unittest.skipUnless(shutil.which("iverilog") and shutil.which("vvp"), "Icarus Verilog is unavailable")
    def test_generated_run_evidence_matches_declared_key_contract(self) -> None:
        schema = json.loads((ROOT / "schemas" / "run-evidence.schema.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            evidence = run_iverilog_simulation(
                [FIXTURES / "counter.sv", FIXTURES / "counter_tb.sv"],
                top="counter_tb",
                artifact_root=directory,
            )
        validate_instance(schema, evidence)
        self.assertTrue(set(schema["required"]).issubset(evidence))
        self.assertTrue(set(evidence).issubset(schema["properties"]))
        self.assertEqual(evidence["schema_version"], schema["properties"]["schema_version"]["const"])

    @unittest.skipUnless(shutil.which("iverilog") and shutil.which("vvp"), "Icarus Verilog is unavailable")
    def test_computed_verification_gate_matches_declared_key_contract(self) -> None:
        schema = json.loads((ROOT / "schemas" / "verification-gate.schema.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            evidence = run_iverilog_simulation(
                [FIXTURES / "counter.sv", FIXTURES / "counter_tb.sv"],
                top="counter_tb",
                artifact_root=directory,
            )
            gate = build_verification_gate(
                [evidence],
                content_hash=evidence["subject_hashes"][0]["content_hash"],
                required_evidence_kinds=("simulation",),
                require_current_artifacts=True,
            )
        validate_instance(schema, gate)
        self.assertEqual(set(gate), set(schema["required"]))
        self.assertEqual(gate["schema_version"], schema["properties"]["schema_version"]["const"])
        self.assertEqual(gate["gate_status"], schema["properties"]["gate_status"]["const"])

    @unittest.skipUnless(shutil.which("iverilog") and shutil.which("vvp"), "Icarus Verilog is unavailable")
    def test_computed_observation_matches_declared_key_contract(self) -> None:
        schema = json.loads((ROOT / "schemas" / "observation-set.schema.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            broken = Path(directory) / "broken.sv"
            broken.write_text("module broken; invalid syntax endmodule\n", encoding="utf-8")
            evidence = run_iverilog_simulation(
                [broken],
                top="broken",
                artifact_root=directory,
            )
            self.assertEqual(evidence["status"], "fail")
            observation = build_observation_set(
                [evidence],
                content_hash=evidence["subject_hashes"][0]["content_hash"],
                require_current_artifacts=True,
            )
        validate_instance(schema, observation)
        self.assertEqual(set(observation), set(schema["required"]))
        self.assertEqual(observation["schema_version"], schema["properties"]["schema_version"]["const"])
        self.assertEqual(observation["observed_statuses"], ["fail"])


if __name__ == "__main__":
    unittest.main()
