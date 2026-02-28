"""Independent packet-adaptation checks for file-level retrieval evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from rtl_ass.compile_manifest import CompileManifest
from rtl_ass.evidence import run_iverilog_simulation, run_verilator_lint
from rtl_ass.integrity import hash_file

CASE_ROOT = Path(__file__).resolve().parent / "workflow_cases" / "packet_tag_skid"
CONSTRAINTS = ("transform", "stability", "reset", "registered-boundary", "throughput")


def grade_packet_stage(workspace: Path, run_root: Path, initial: Mapping[str, str]) -> dict[str, Any]:
    relative = "rtl/packet_tag_skid.sv"
    rtl = workspace / relative
    if not rtl.is_file() or rtl.is_symlink():
        return {"correct": False, "error": "required_candidate_file_missing"}
    digest = hash_file(rtl)
    checks = {}
    evidence = []
    for index, constraint in enumerate(CONSTRAINTS):
        runs = []
        for width, tags in ((1, 1), (13, 3), (32, 5)):
            manifest = CompileManifest.create(
                [rtl, CASE_ROOT / "private" / "packet_tag_skid_tb.sv"],
                "packet_tag_skid_tb",
                parameters=[f"W={width}", f"T={tags}", f"CHECK={index}"],
            )
            run = run_iverilog_simulation(manifest, artifact_root=run_root / "grader-evidence")
            runs.append(run)
            evidence.append(run)
        checks[constraint] = {
            "status": _constraint_status(runs, index),
            "target": relative,
            "target_hash": digest,
            "evidence_file_hash": hash_file(Path(runs[0]["evidence_file"])) if "evidence_file" in runs[0] else None,
            "evidence_file_hashes": [hash_file(Path(run["evidence_file"])) for run in runs if "evidence_file" in run],
        }
    lint = run_verilator_lint([rtl], top="packet_tag_skid", artifact_root=run_root / "grader-evidence")
    evidence.append(lint)
    protected = all(
        (workspace / path).is_file() and not (workspace / path).is_symlink() and hash_file(workspace / path) == digest
        for path, digest in initial.items()
        if path not in {"repository_head", relative}
    )
    return {
        "correct": protected and lint["status"] == "pass" and all(c["status"] == "pass" for c in checks.values()),
        "grader_statuses": {"lint": lint["status"], **{key: value["status"] for key, value in checks.items()}},
        "candidate_hashes": {relative: digest},
        "protected_files_unchanged": protected,
        "application_constraints": checks,
        "expected_agent_evidence_subjects": {"lint": [digest]},
        "evidence": [
            {
                "kind": run["kind"],
                "status": run["status"],
                "input_hash": run["input_hash"],
                "evidence_file": run.get("evidence_file"),
                "evidence_file_hash": hash_file(Path(run["evidence_file"])) if "evidence_file" in run else None,
            }
            for run in evidence
        ],
    }


def _constraint_status(runs: list[dict[str, Any]], index: int) -> str:
    statuses = {run["status"] for run in runs}
    if "not_available" in statuses:
        return "not_available"
    if statuses != {"pass"}:
        return "fail" if "fail" in statuses else "not_evaluated"
    # A candidate's premature $finish must not make an unexecuted checker pass.
    marker = f"PACKET_CHECK_PASS {index}"
    return (
        "pass"
        if all(
            marker in (Path(run["evidence_file"]).parent / "run.stdout.log").read_text(encoding="utf-8").splitlines()
            for run in runs
        )
        else "fail"
    )
