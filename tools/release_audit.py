#!/usr/bin/env python3
"""Run the representative RTL-ASS 1.3 open-tool and knowledge release audit."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from rtl_ass.evidence import (
    run_iverilog_simulation,
    run_opensta,
    run_verilator_lint,
    run_verilator_simulation,
    run_yosys_equivalence,
    run_yosys_formal,
    run_yosys_synthesis,
)
from rtl_ass.integrity import utc_now
from rtl_ass.kb import KnowledgeDatabase
from rtl_ass.kb.packs import load_knowledge_pack
from rtl_ass.kb.retrieval import build_retrieval_receipt, validate_retrieval_receipt, write_retrieval_receipt
from rtl_ass.tools import discover_tools
from rtl_ass.waveform import first_divergence_waveform, query_waveform
from rtl_ass.workflow import summarize_verification_plan, validate_verification_plan

ROOT = Path(__file__).resolve().parents[1]
RELEASE_VERSION = "1.3.0"


def _expect(result: dict[str, Any], expected: str, label: str) -> dict[str, Any]:
    if result.get("status") != expected:
        raise RuntimeError(f"{label} expected {expected}, got {result.get('status')}")
    return result


def run_audit(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    run_root = Path(tempfile.mkdtemp(prefix="run-", dir=output))
    starter = ROOT / "library" / "starter"
    rtl = starter / "rtl" / "ready_valid_register.sv"
    tb = starter / "tb" / "ready_valid_register_tb.sv"
    formal = starter / "assertions" / "ready_valid_register_formal.sv"
    fixtures = ROOT / "tests" / "fixtures"
    sta_fixtures = ROOT / "tests" / "sta_fixtures"

    evidence_root = run_root / "evidence"
    checks: dict[str, Any] = {}
    checks["lint"] = _expect(
        run_verilator_lint([rtl], top="ready_valid_register", artifact_root=evidence_root), "pass", "lint"
    )
    checks["simulation"] = _expect(
        run_iverilog_simulation([rtl, tb], top="ready_valid_register_tb", artifact_root=evidence_root),
        "pass",
        "simulation",
    )
    checks["verilator_simulation"] = _expect(
        run_verilator_simulation(
            [fixtures / "counter.sv", fixtures / "counter_tb.sv"],
            top="counter_tb",
            artifact_root=evidence_root,
        ),
        "pass",
        "Verilator simulation",
    )
    checks["synthesis"] = _expect(
        run_yosys_synthesis([rtl], top="ready_valid_register", artifact_root=evidence_root),
        "pass",
        "synthesis",
    )
    checks["mapped_synthesis"] = _expect(
        run_yosys_synthesis(
            [sta_fixtures / "sta_netlist.v"],
            top="sta_top",
            liberty=sta_fixtures / "sta.lib",
            artifact_root=evidence_root,
        ),
        "pass",
        "mapped synthesis",
    )
    checks["formal_pass"] = _expect(
        run_yosys_formal(
            [rtl, formal],
            top="ready_valid_register_formal",
            depth=4,
            initialization="defined",
            artifact_root=evidence_root,
        ),
        "pass",
        "formal pass",
    )
    checks["formal_counterexample"] = _expect(
        run_yosys_formal(
            [fixtures / "formal_fail.sv"],
            top="formal_fail",
            depth=3,
            initialization="defined",
            artifact_root=evidence_root,
        ),
        "fail",
        "formal counterexample",
    )
    checks["equivalence_pass"] = _expect(
        run_yosys_equivalence(
            reference_sources=[fixtures / "equiv_reference.sv"],
            implementation_sources=[fixtures / "equiv_implementation.sv"],
            reference_top="equiv_reference",
            implementation_top="equiv_implementation",
            depth=1,
            artifact_root=evidence_root,
        ),
        "pass",
        "equivalence pass",
    )
    checks["equivalence_mismatch"] = _expect(
        run_yosys_equivalence(
            reference_sources=[fixtures / "equiv_reference.sv"],
            implementation_sources=[fixtures / "equiv_mismatch.sv"],
            reference_top="equiv_reference",
            implementation_top="equiv_mismatch",
            depth=1,
            artifact_root=evidence_root,
        ),
        "fail",
        "equivalence mismatch",
    )
    checks["sta"] = _expect(
        run_opensta(
            netlist=sta_fixtures / "sta_netlist.v",
            liberty=sta_fixtures / "sta.lib",
            constraints=sta_fixtures / "sta.sdc",
            top="sta_top",
            artifact_root=evidence_root,
        ),
        "pass",
        "STA",
    )
    mapped_netlists = [Path(path) for path in checks["mapped_synthesis"]["artifacts"] if Path(path).name == "netlist.v"]
    if len(mapped_netlists) != 1:
        raise RuntimeError("mapped synthesis did not produce exactly one Verilog netlist")
    checks["mapped_sta"] = _expect(
        run_opensta(
            netlist=mapped_netlists[0],
            liberty=sta_fixtures / "sta.lib",
            constraints=sta_fixtures / "sta.sdc",
            top="sta_top",
            artifact_root=evidence_root,
        ),
        "pass",
        "mapped STA",
    )

    waveform = fixtures / "divergence.vcd"
    checks["vcd_query"] = query_waveform(waveform, patterns=("tb.expected", "tb.actual"), max_events=50)
    checks["vcd_divergence"] = first_divergence_waveform(
        waveform, expected="tb.expected", actual="tb.actual", max_events=50
    )
    if checks["vcd_divergence"].get("status") != "found":
        raise RuntimeError("VCD fixture did not produce the expected divergence")

    converter = shutil.which("vcd2fst")
    if converter is None:
        raise RuntimeError("vcd2fst is required for the 1.1 release audit")
    fst = run_root / "divergence.fst"
    subprocess.run([converter, str(waveform), str(fst)], check=True, capture_output=True)
    checks["fst_query"] = query_waveform(fst, patterns=("tb.expected", "tb.actual"), max_events=50)
    checks["fst_divergence"] = first_divergence_waveform(fst, expected="tb.expected", actual="tb.actual", max_events=50)
    if checks["fst_divergence"].get("status") != "found":
        raise RuntimeError("FST fixture did not produce the expected divergence")

    verification_plan = validate_verification_plan(
        {
            "schema_version": "1.0",
            "plan_id": "release-starter",
            "task_class": "verification",
            "claims": [
                {
                    "id": "lint",
                    "statement": "The starter RTL passes lint.",
                    "evidence_kind": "lint",
                    "requirement": "required",
                    "expected_status": "pass",
                },
                {
                    "id": "simulation",
                    "statement": "The starter self-checking simulation passes.",
                    "evidence_kind": "simulation",
                    "requirement": "required",
                    "expected_status": "pass",
                },
            ],
            "stop_policy": {"max_retries_per_claim": 0, "max_parallel_eda": 1},
        }
    )
    checks["verification_workflow"] = summarize_verification_plan(
        verification_plan,
        [
            f"lint={checks['lint']['evidence_file']}",
            f"simulation={checks['simulation']['evidence_file']}",
        ],
    )
    if not checks["verification_workflow"]["ready_to_stop"]:
        raise RuntimeError("starter verification workflow did not reach its required stopping gate")

    pack = load_knowledge_pack(starter / "pack.json")
    database = KnowledgeDatabase(run_root / "starter.db")
    database.initialize(actor="release-audit")
    imported = database.import_pack(starter / "pack.json", namespace="builtin:starter", actor="release-audit")
    repeated = database.import_pack(starter / "pack.json", namespace="builtin:starter", actor="release-audit")
    audit_chain = database.verify_audit_chain()
    if imported["created_count"] != 5 or repeated["created_count"] != 0 or not audit_chain["valid"]:
        raise RuntimeError("starter knowledge-pack transaction or audit-chain check failed")
    retrieval_query = "ready absent-token"
    if database.search(
        retrieval_query,
        namespaces=["builtin:starter"],
        limit=3,
        match_mode="all",
    ):
        raise RuntimeError("strict all-token retrieval unexpectedly matched an absent term")
    retrieval_results = database.search(
        retrieval_query,
        namespaces=["builtin:starter"],
        limit=3,
        match_mode="any",
    )
    retrieval_receipt = build_retrieval_receipt(
        retrieval_results,
        actor="release-audit",
        query=retrieval_query,
        namespaces=["builtin:starter"],
        limit=3,
        role=None,
        status=None,
        match_mode="any",
    )
    retrieval_path = write_retrieval_receipt(retrieval_receipt, run_root / "retrieval.json")
    checks["retrieval"] = validate_retrieval_receipt(json.loads(retrieval_path.read_text(encoding="utf-8")))
    if checks["retrieval"]["result_count"] < 1:
        raise RuntimeError("explicit any-token retrieval did not return the expected bounded card")

    summary = {
        "schema_version": "1.0",
        "release": RELEASE_VERSION,
        "generated_at": utc_now(),
        "status": "pass",
        "tool_discovery": discover_tools(),
        "checks": checks,
        "knowledge_pack": {
            "pack_hash": pack["pack_hash"],
            "created_count": imported["created_count"],
            "idempotent_created_count": repeated["created_count"],
            "audit_chain": audit_chain,
        },
    }
    (output / "release-audit.json").write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "release-evidence")
    arguments = parser.parse_args()
    summary = run_audit(arguments.output.resolve())
    print(json.dumps({"status": summary["status"], "output": str(arguments.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
