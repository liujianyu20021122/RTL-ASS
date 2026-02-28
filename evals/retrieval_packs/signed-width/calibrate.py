#!/usr/bin/env python3
"""Build an ignored calibrated evaluation database from the signed-width card."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rtl_ass.integrity import canonical_json, hash_bytes, hash_file
from rtl_ass.kb import KnowledgeDatabase, RecordStatus

EVALS_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = EVALS_ROOT.parent
PACK_ROOT = EVALS_ROOT / "retrieval_packs" / "signed-width"
RELEVANT_PACK = PACK_ROOT / "pack.json"
RELEVANT_CARD = PACK_ROOT / "cards" / "signed-expression-audit.md"
SIGNED_CALIBRATION = PACK_ROOT / "calibration" / "signed_width_calibration.sv"
IRRELEVANT_PACK = PACK_ROOT / "plausible-irrelevant-pack.json"
IRRELEVANT_CARD = PACK_ROOT / "cards" / "ready-valid-payload-width.md"
READY_VALID_RTL = REPOSITORY_ROOT / "library" / "starter" / "rtl" / "ready_valid_register.sv"
READY_VALID_TB = REPOSITORY_ROOT / "library" / "starter" / "tb" / "ready_valid_register_tb.sv"
READY_VALID_MUTATION = ("else if (in_ready) begin", "else if (in_valid) begin")


@dataclass(frozen=True)
class SimulationOutcome:
    commands: tuple[tuple[str, ...], ...]
    logs: tuple[Path, ...]
    compile_returncode: int
    run_returncode: int


@dataclass(frozen=True)
class CalibrationOutcome:
    pack: Path
    card: Path
    subjects: tuple[Path, ...]
    commands: tuple[tuple[str, ...], ...]
    artifacts: tuple[Path, ...]
    top: str
    summary: dict[str, Any]


def _run(command: list[str], *, output: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, check=False, capture_output=True, text=True, timeout=60)
    output.write_text(result.stdout + result.stderr, encoding="utf-8")
    return result


def _tool_version(executable: str) -> str:
    result = subprocess.run([executable, "-V"], check=False, capture_output=True, text=True, timeout=10)
    output = result.stdout + result.stderr
    return next((line.strip() for line in output.splitlines() if line.strip()), "unknown")


def _simulate(
    *,
    name: str,
    sources: tuple[Path, ...],
    top: str,
    artifacts: Path,
    iverilog: str,
    vvp: str,
) -> SimulationOutcome:
    executable = artifacts / f"{name}.vvp"
    compile_log = artifacts / f"{name}-compile.log"
    run_log = artifacts / f"{name}-run.log"
    compile_command = (
        iverilog,
        "-g2012",
        "-s",
        top,
        "-o",
        executable.as_posix(),
        *(path.as_posix() for path in sources),
    )
    run_command = (vvp, executable.as_posix())
    compile_result = _run(list(compile_command), output=compile_log, cwd=artifacts)
    if compile_result.returncode != 0 or not executable.is_file():
        raise RuntimeError(f"{name} calibration compilation failed")
    run_result = _run(list(run_command), output=run_log, cwd=artifacts)
    return SimulationOutcome(
        commands=(compile_command, run_command),
        logs=(compile_log, run_log),
        compile_returncode=compile_result.returncode,
        run_returncode=run_result.returncode,
    )


def _calibrate_relevant(artifacts: Path, *, iverilog: str, vvp: str) -> CalibrationOutcome:
    simulation = _simulate(
        name="signed-width-calibration",
        sources=(SIGNED_CALIBRATION,),
        top="signed_width_calibration",
        artifacts=artifacts,
        iverilog=iverilog,
        vvp=vvp,
    )
    run_log = simulation.logs[-1]
    if simulation.run_returncode != 0 or "SIGNED_WIDTH_CALIBRATION_PASS" not in run_log.read_text(encoding="utf-8"):
        raise RuntimeError("signed-width calibration mutation test failed")
    return CalibrationOutcome(
        pack=RELEVANT_PACK,
        card=RELEVANT_CARD,
        subjects=(RELEVANT_CARD, SIGNED_CALIBRATION),
        commands=simulation.commands,
        artifacts=simulation.logs,
        top="signed_width_calibration",
        summary={
            "compile_returncode": simulation.compile_returncode,
            "method": "exhaustive 4-bit operand pairs plus a narrow-intermediate mutation",
            "limitations": "validates the card's sizing and saturation guidance, not every SystemVerilog context rule",
            "run_returncode": simulation.run_returncode,
        },
    )


def _calibrate_plausible_irrelevant(artifacts: Path, *, iverilog: str, vvp: str) -> CalibrationOutcome:
    baseline = _simulate(
        name="ready-valid-baseline",
        sources=(READY_VALID_RTL, READY_VALID_TB),
        top="ready_valid_register_tb",
        artifacts=artifacts,
        iverilog=iverilog,
        vvp=vvp,
    )
    baseline_log = baseline.logs[-1]
    if baseline.run_returncode != 0 or "PASS: ready_valid_register" not in baseline_log.read_text(encoding="utf-8"):
        raise RuntimeError("ready/valid negative-control baseline failed")

    source = READY_VALID_RTL.read_text(encoding="utf-8")
    before, after = READY_VALID_MUTATION
    if source.count(before) != 1 or after in source:
        raise RuntimeError("ready/valid calibration mutation precondition is not exact")
    mutant = artifacts / "ready_valid_register_mutant.sv"
    mutant.write_text(source.replace(before, after), encoding="utf-8")
    mutation = _simulate(
        name="ready-valid-mutation",
        sources=(mutant, READY_VALID_TB),
        top="ready_valid_register_tb",
        artifacts=artifacts,
        iverilog=iverilog,
        vvp=vvp,
    )
    if mutation.run_returncode == 0:
        raise RuntimeError("ready/valid calibration failed to reject a backpressure mutation")
    return CalibrationOutcome(
        pack=IRRELEVANT_PACK,
        card=IRRELEVANT_CARD,
        subjects=(IRRELEVANT_CARD, READY_VALID_RTL, READY_VALID_TB),
        commands=(*baseline.commands, *mutation.commands),
        artifacts=(*baseline.logs, mutant, *mutation.logs),
        top="ready_valid_register_tb",
        summary={
            "baseline_compile_returncode": baseline.compile_returncode,
            "baseline_run_returncode": baseline.run_returncode,
            "method": "passing baseline plus rejection of a payload-stability backpressure mutation",
            "limitations": "calibrates ready/valid payload transport only; it does not validate signed arithmetic",
            "mutation_compile_returncode": mutation.compile_returncode,
            "mutation_run_returncode": mutation.run_returncode,
        },
    )


def build_database(destination: Path, *, treatment: str = "relevant") -> dict[str, Any]:
    if destination.exists() or destination.is_symlink():
        raise RuntimeError(f"refusing to overwrite evaluation database: {destination}")
    iverilog = shutil.which("iverilog")
    vvp = shutil.which("vvp")
    if iverilog is None or vvp is None:
        raise RuntimeError("signed-width calibration requires project-local iverilog and vvp")
    artifacts = destination.with_suffix(".artifacts")
    artifacts.mkdir(parents=True)
    started = datetime.now(UTC).isoformat()
    if treatment == "relevant":
        calibration = _calibrate_relevant(artifacts, iverilog=iverilog, vvp=vvp)
    elif treatment == "plausible-irrelevant":
        calibration = _calibrate_plausible_irrelevant(artifacts, iverilog=iverilog, vvp=vvp)
    else:
        raise ValueError(f"unsupported retrieval treatment: {treatment}")
    finished = datetime.now(UTC).isoformat()

    database = KnowledgeDatabase(destination)
    database.initialize(actor="evaluation-curator")
    imported = database.import_pack(calibration.pack, namespace="eval:retrieval", actor="evaluation-curator")
    if len(imported["records"]) != 1:
        raise RuntimeError("signed-width calibration expects exactly one imported card")
    record_id = str(imported["records"][0]["id"])
    database.transition(record_id, RecordStatus.ANALYZED, actor="evaluation-curator")
    database.transition(record_id, RecordStatus.CANDIDATE, actor="evaluation-curator")

    commands = [list(command) for command in calibration.commands]
    input_hash = hash_bytes(
        canonical_json(
            {
                "subjects": [
                    {"path": path.relative_to(REPOSITORY_ROOT).as_posix(), "content_hash": hash_file(path)}
                    for path in calibration.subjects
                ],
                "commands": commands,
            }
        ).encode("utf-8")
    )
    evidence_file = artifacts / "run-evidence.json"
    evidence = {
        "schema_version": "1.0",
        "kind": "mutation",
        "status": "pass",
        "tool": {"name": "iverilog+vvp", "version": _tool_version(iverilog)},
        "input_hash": input_hash,
        "subject_hashes": [
            {"index": index, "path": path.as_posix(), "content_hash": hash_file(path)}
            for index, path in enumerate(calibration.subjects)
        ],
        "commands": commands,
        "artifacts": [path.as_posix() for path in calibration.artifacts],
        "artifact_hashes": [
            {"index": index, "path": path.as_posix(), "content_hash": hash_file(path)}
            for index, path in enumerate(calibration.artifacts)
        ],
        "top": calibration.top,
        "claim_scope": "tool execution evidence only",
        "evidence_file": evidence_file.as_posix(),
        "started_at": started,
        "finished_at": finished,
        "summary": {"treatment": treatment, **calibration.summary},
    }
    evidence_file.write_text(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    database.verify_record(
        record_id,
        [evidence],
        actor="evaluation-curator",
        required_evidence_kinds=["mutation"],
    )
    return {
        "schema_version": "1.0",
        "database": destination.as_posix(),
        "database_hash": hash_file(destination),
        "record_id": record_id,
        "record_status": database.get_record(record_id)["status"],
        "treatment": treatment,
        "audit_chain": database.verify_audit_chain(),
        "evidence_file": evidence_file.as_posix(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--treatment", choices=("relevant", "plausible-irrelevant"), default="relevant")
    args = parser.parse_args()
    result = build_database(args.output.absolute(), treatment=args.treatment)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
