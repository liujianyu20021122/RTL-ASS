"""Build an isolated, behavior-calibrated source-file treatment from the pinned main record."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evals.retrieval_treatment import validate_retrieval_treatment
from evals.run_codex_ab import _retrieval_case_identity, _validate_retrieval_ablation_database
from evals.workflow_cases import get_case
from rtl_ass.compile_manifest import CompileManifest
from rtl_ass.evidence import run_iverilog_simulation
from rtl_ass.integrity import hash_file
from rtl_ass.kb import KnowledgeDatabase, KnowledgeRecordInput, LicenseStatus, RecordRole, RecordStatus

PACK_ROOT = Path(__file__).resolve().parent


def build_database(source_database: Path, output: Path) -> dict[str, Any]:
    source_hash = hash_file(source_database)
    source = KnowledgeDatabase(source_database)
    if not source.verify_audit_chain()["valid"]:
        raise ValueError("source database audit is invalid")
    manifest = json.loads((PACK_ROOT / "source.json").read_text(encoding="utf-8"))
    record = source.get_record(manifest["record_id"], include_content=True)
    for key in (
        "source_uri",
        "source_revision",
        "source_path",
        "content_hash",
        "license_spdx",
        "license_status",
        "role",
        "status",
    ):
        if record[key] != manifest[key]:
            raise ValueError(f"pinned source identity differs: {key}")
    artifacts = output.with_suffix(".artifacts")
    treatment_path = output.with_suffix(".treatment.json")
    if any(path.exists() or path.is_symlink() for path in (output, artifacts, treatment_path)):
        raise ValueError("refusing to overwrite calibration outputs")
    artifacts.mkdir(parents=True)
    rtl = artifacts / "axis_register.v"
    rtl.write_text(record["content"], encoding="utf-8")
    if hash_file(rtl) != manifest["content_hash"]:
        raise ValueError("source content hash mismatch")
    tb = PACK_ROOT / "axis_calibration_tb.sv"
    baseline = run_iverilog_simulation(
        CompileManifest.create([rtl, tb], "axis_calibration_tb", parameters=["MODE=2"]),
        artifact_root=artifacts,
    )
    mutation = run_iverilog_simulation(
        CompileManifest.create([rtl, tb], "axis_calibration_tb", parameters=["MODE=1"]),
        artifact_root=artifacts,
    )
    if baseline["status"] != "pass" or mutation["status"] != "fail":
        raise ValueError(
            f"calibration requires passing skid mode and rejected bubble mode: {baseline['status']}/{mutation['status']}"
        )
    # Require a runtime behavioral failure, not a compilation/infrastructure error.
    mutation_log = Path(mutation["evidence_file"]).parent / "run.stdout.log"
    if "mode introduces bubbles" not in mutation_log.read_text(encoding="utf-8"):
        raise ValueError("mutation did not fail for the expected behavioral reason")
    database = KnowledgeDatabase(output)
    database.initialize(actor=manifest["reviewer"])
    imported = database.add_record(
        KnowledgeRecordInput(
            namespace="eval:retrieval",
            role=RecordRole.RTL_DESIGN,
            language="verilog",
            title="axis_register skid buffer ready valid backpressure registered boundary reset throughput",
            summary="Pinned upstream transport source; REG_TYPE=2 skid mode, sideband enable parameters, active-high synchronous reset. Adapt assumptions explicitly; does not implement packet transformations.",
            content=record["content"],
            source_uri=record["source_uri"],
            source_revision=record["source_revision"],
            source_path=record["source_path"],
            license_spdx=record["license_spdx"],
            license_status=LicenseStatus.KNOWN,
            metadata={
                "contamination_review": manifest["contamination_review"],
                "source_database_hash": source_hash,
                "source_record_id": record["id"],
                "review_basis": manifest["review_basis"],
                "calibration_scope": "13-bit payload, enabled sidebands, skid mode stalls, full throughput and reset flush; not all parameter configurations",
                "mutation_evidence_hash": hash_file(Path(mutation["evidence_file"])),
            },
        ),
        actor=manifest["reviewer"],
    )
    record_id = imported["record"]["id"]
    database.transition(record_id, RecordStatus.ANALYZED, actor=manifest["reviewer"])
    database.transition(record_id, RecordStatus.CANDIDATE, actor=manifest["reviewer"])
    database.verify_record(record_id, [baseline], actor=manifest["reviewer"], required_evidence_kinds=["simulation"])
    case = get_case("packet-tag-skid")
    audit = _validate_retrieval_ablation_database(output, case)
    treatment = validate_retrieval_treatment(
        {
            "schema_version": "1.0",
            "case_identity": _retrieval_case_identity(case),
            "treatment": "relevant",
            "record_content_hashes": [record["content_hash"]],
            "query_concepts": ["backpressure", "registered boundary", "reset", "skid", "throughput"],
            "decision_targets": ["registered-boundary", "reset", "stability", "throughput"],
            "plausible_overlap": [],
            "applicability_claims": [
                "Skid storage preserves enabled sidebands and throughput across a registered ready boundary."
            ],
            "non_applicability_claims": [
                "Upstream active-high reset, AXIS enable defaults and absent packet transforms cannot be copied as the task contract."
            ],
            "contamination_review": manifest["contamination_review"],
            "reviewer": manifest["reviewer"],
            "reviewed_at": manifest["reviewed_at"],
        },
        expected_case_identity=_retrieval_case_identity(case),
        calibrated_record_hashes=audit["record_content_hashes"],
    )
    treatment_path.write_text(json.dumps(treatment, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if hash_file(source_database) != source_hash:
        raise ValueError("main database changed during calibration")
    return {
        "database": str(output),
        "database_hash": hash_file(output),
        "treatment_manifest": str(treatment_path),
        "source_record_id": record["id"],
        "record_id": record_id,
        "source_content_hash": record["content_hash"],
        "audit": audit,
        "baseline_evidence": baseline["evidence_file"],
        "mutation_evidence": mutation["evidence_file"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_database(args.source_database.resolve(), args.output.resolve()), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
