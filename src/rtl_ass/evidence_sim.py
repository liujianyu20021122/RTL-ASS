"""Verilator lint and Icarus Verilog simulation evidence."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Sequence

from rtl_ass.evidence_common import (
    SourceBundle,
    base_evidence,
    input_stable_status,
    run_directory,
    timeout_text,
    tool_version,
    unavailable_evidence,
    validate_timeout,
    write_evidence,
)
from rtl_ass.integrity import utc_now


def run_verilator_lint(
    sources: Sequence[str | Path],
    *,
    top: str,
    artifact_root: str | Path,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    bundle = SourceBundle.create(sources, top)
    validate_timeout(timeout_seconds)
    executable = shutil.which("verilator")
    if executable is None:
        return unavailable_evidence(kind="lint", tool_name="verilator", bundle=bundle)
    version = tool_version(executable, ["--version"])
    current_run = run_directory(artifact_root, "lint", "verilator")
    stdout_path = current_run / "stdout.log"
    stderr_path = current_run / "stderr.log"
    command = [executable, "--lint-only", "--timing", "--top-module", bundle.top, *map(str, bundle.sources)]
    started_at = utc_now()
    try:
        result = subprocess.run(
            command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout_seconds
        )
        status = "pass" if result.returncode == 0 else "fail"
        summary = {"returncode": result.returncode}
        stdout = result.stdout
        stderr = result.stderr
    except subprocess.TimeoutExpired as exc:
        status = "timeout"
        summary = {"timeout_seconds": timeout_seconds}
        stdout = timeout_text(exc.stdout)
        stderr = timeout_text(exc.stderr)
    finished_at = utc_now()
    status, summary = input_stable_status(bundle, status, summary)
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    evidence = base_evidence(
        kind="lint",
        status=status,
        tool_name="verilator",
        tool_version_value=version,
        bundle=bundle,
        commands=[command],
        artifacts=[stdout_path.as_posix(), stderr_path.as_posix()],
        started_at=started_at,
        finished_at=finished_at,
        summary=summary,
    )
    return write_evidence(current_run, evidence)


def run_iverilog_simulation(
    sources: Sequence[str | Path],
    *,
    top: str,
    artifact_root: str | Path,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    bundle = SourceBundle.create(sources, top)
    validate_timeout(timeout_seconds)
    compiler = shutil.which("iverilog")
    runtime = shutil.which("vvp")
    if compiler is None or runtime is None:
        return unavailable_evidence(
            kind="simulation",
            tool_name="iverilog-vvp",
            bundle=bundle,
            summary={"iverilog": compiler is not None, "vvp": runtime is not None},
        )
    version = tool_version(compiler, ["-V"])
    current_run = run_directory(artifact_root, "simulation", "iverilog")
    executable_path = current_run / "simulation.vvp"
    compile_command = [compiler, "-g2012", "-s", bundle.top, "-o", str(executable_path), *map(str, bundle.sources)]
    started_at = utc_now()
    try:
        compile_result = subprocess.run(
            compile_command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        finished_at = utc_now()
        compile_stdout_path = current_run / "compile.stdout.log"
        compile_stderr_path = current_run / "compile.stderr.log"
        compile_stdout_path.write_text(timeout_text(exc.stdout), encoding="utf-8")
        compile_stderr_path.write_text(timeout_text(exc.stderr), encoding="utf-8")
        status, summary = input_stable_status(
            bundle,
            "timeout",
            {"phase": "compile", "timeout_seconds": timeout_seconds},
        )
        evidence = base_evidence(
            kind="simulation",
            status=status,
            tool_name="iverilog-vvp",
            tool_version_value=version,
            bundle=bundle,
            commands=[compile_command],
            artifacts=[compile_stdout_path.as_posix(), compile_stderr_path.as_posix()],
            started_at=started_at,
            finished_at=finished_at,
            summary=summary,
        )
        return write_evidence(current_run, evidence)

    compile_stdout_path = current_run / "compile.stdout.log"
    compile_stderr_path = current_run / "compile.stderr.log"
    compile_stdout_path.write_text(compile_result.stdout, encoding="utf-8")
    compile_stderr_path.write_text(compile_result.stderr, encoding="utf-8")
    artifacts = [compile_stdout_path.as_posix(), compile_stderr_path.as_posix()]
    if compile_result.returncode != 0:
        status, summary = input_stable_status(
            bundle,
            "fail",
            {"phase": "compile", "compile_returncode": compile_result.returncode},
        )
        evidence = base_evidence(
            kind="simulation",
            status=status,
            tool_name="iverilog-vvp",
            tool_version_value=version,
            bundle=bundle,
            commands=[compile_command],
            artifacts=artifacts,
            started_at=started_at,
            finished_at=utc_now(),
            summary=summary,
        )
        return write_evidence(current_run, evidence)

    run_command = [runtime, str(executable_path)]
    try:
        run_result = subprocess.run(
            run_command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
        )
        status = "pass" if run_result.returncode == 0 else "fail"
        run_stdout = run_result.stdout
        run_stderr = run_result.stderr
        summary = {
            "phase": "run",
            "compile_returncode": compile_result.returncode,
            "run_returncode": run_result.returncode,
        }
    except subprocess.TimeoutExpired as exc:
        status = "timeout"
        run_stdout = timeout_text(exc.stdout)
        run_stderr = timeout_text(exc.stderr)
        summary = {"phase": "run", "compile_returncode": compile_result.returncode, "timeout_seconds": timeout_seconds}
    run_stdout_path = current_run / "run.stdout.log"
    run_stderr_path = current_run / "run.stderr.log"
    run_stdout_path.write_text(run_stdout, encoding="utf-8")
    run_stderr_path.write_text(run_stderr, encoding="utf-8")
    artifacts.extend([executable_path.as_posix(), run_stdout_path.as_posix(), run_stderr_path.as_posix()])
    status, summary = input_stable_status(bundle, status, summary)
    evidence = base_evidence(
        kind="simulation",
        status=status,
        tool_name="iverilog-vvp",
        tool_version_value=version,
        bundle=bundle,
        commands=[compile_command, run_command],
        artifacts=artifacts,
        started_at=started_at,
        finished_at=utc_now(),
        summary=summary,
    )
    return write_evidence(current_run, evidence)
