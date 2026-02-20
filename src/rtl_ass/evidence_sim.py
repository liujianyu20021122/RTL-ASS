"""Verilator and Icarus Verilog lint/simulation evidence adapters."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from rtl_ass.compile_manifest import (
    CompileInput,
    CompileManifest,
    coerce_compile_manifest,
    iverilog_compile_arguments,
    verilator_compile_arguments,
)
from rtl_ass.evidence_common import (
    ToolVersionProbe,
    base_evidence,
    input_stable_status,
    run_directory,
    run_tool_command,
    tool_version,
    unavailable_evidence,
    validate_timeout,
    write_evidence,
)
from rtl_ass.integrity import utc_now


def run_verilator_lint(
    sources: CompileInput,
    *,
    top: str | None = None,
    artifact_root: str | Path,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    bundle = coerce_compile_manifest(sources, top)
    validate_timeout(timeout_seconds)
    executable = shutil.which("verilator")
    if executable is None:
        return unavailable_evidence(kind="lint", tool_name="verilator", bundle=bundle)
    version = tool_version(executable, ["--version"])
    current_run = run_directory(artifact_root, "lint", "verilator")
    stdout_path = current_run / "stdout.log"
    stderr_path = current_run / "stderr.log"
    command = [
        executable,
        "--lint-only",
        "--timing",
        "--top-module",
        bundle.top,
        *verilator_compile_arguments(bundle),
        *map(str, bundle.compilation_units),
    ]
    started_at = utc_now()
    result = run_tool_command(command, timeout_seconds=timeout_seconds)
    if result.outcome == "timeout":
        status = "timeout"
        summary = {"timeout_seconds": timeout_seconds, "compile_manifest": bundle.option_summary()}
    elif result.outcome == "launch_failed":
        status = "blocked"
        summary = {
            "launch_failed": True,
            "launch_error": result.error_type,
            "compile_manifest": bundle.option_summary(),
        }
    else:
        returncode = result.completed_returncode()
        status = "pass" if returncode == 0 else "fail"
        summary = {"returncode": returncode, "compile_manifest": bundle.option_summary()}
    stdout = result.stdout
    stderr = result.stderr
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
    sources: CompileInput,
    *,
    top: str | None = None,
    artifact_root: str | Path,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    bundle = coerce_compile_manifest(sources, top)
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
    current_run = run_directory(artifact_root, "simulation", "iverilog")
    executable_path = current_run / "simulation.vvp"
    compile_command = [
        compiler,
        *iverilog_compile_arguments(bundle),
        "-s",
        bundle.top,
        "-o",
        str(executable_path),
        *map(str, bundle.compilation_units),
    ]
    return _run_compiled_simulation(
        bundle=bundle,
        current_run=current_run,
        compile_command=compile_command,
        run_command=[runtime, str(executable_path)],
        executable_path=executable_path,
        tool_name="iverilog-vvp",
        tool_version_value=tool_version(compiler, ["-V"]),
        timeout_seconds=timeout_seconds,
    )


def run_verilator_simulation(
    sources: CompileInput,
    *,
    top: str | None = None,
    artifact_root: str | Path,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    bundle = coerce_compile_manifest(sources, top)
    validate_timeout(timeout_seconds)
    compiler = shutil.which("verilator")
    if compiler is None:
        return unavailable_evidence(kind="simulation", tool_name="verilator-binary", bundle=bundle)
    current_run = run_directory(artifact_root, "simulation", "verilator")
    object_directory = current_run / "obj"
    executable_path = object_directory / "simulation"
    compile_command = [
        compiler,
        "--binary",
        "--timing",
        "--top-module",
        bundle.top,
        "--Mdir",
        str(object_directory),
        "-o",
        executable_path.name,
        *verilator_compile_arguments(bundle),
        *map(str, bundle.compilation_units),
    ]
    return _run_compiled_simulation(
        bundle=bundle,
        current_run=current_run,
        compile_command=compile_command,
        run_command=[str(executable_path)],
        executable_path=executable_path,
        tool_name="verilator-binary",
        tool_version_value=tool_version(compiler, ["--version"]),
        timeout_seconds=timeout_seconds,
    )


def _run_compiled_simulation(
    *,
    bundle: CompileManifest,
    current_run: Path,
    compile_command: list[str],
    run_command: list[str],
    executable_path: Path,
    tool_name: str,
    tool_version_value: str | ToolVersionProbe,
    timeout_seconds: int,
) -> dict[str, Any]:
    compile_stdout_path = current_run / "compile.stdout.log"
    compile_stderr_path = current_run / "compile.stderr.log"
    started_at = utc_now()
    compile_result = run_tool_command(compile_command, timeout_seconds=timeout_seconds)
    compile_stdout_path.write_text(compile_result.stdout, encoding="utf-8")
    compile_stderr_path.write_text(compile_result.stderr, encoding="utf-8")
    if compile_result.outcome == "timeout":
        status, summary = input_stable_status(
            bundle,
            "timeout",
            {
                "phase": "compile",
                "timeout_seconds": timeout_seconds,
                "compile_manifest": bundle.option_summary(),
            },
        )
        return write_evidence(
            current_run,
            base_evidence(
                kind="simulation",
                status=status,
                tool_name=tool_name,
                tool_version_value=tool_version_value,
                bundle=bundle,
                commands=[compile_command],
                artifacts=[compile_stdout_path.as_posix(), compile_stderr_path.as_posix()],
                started_at=started_at,
                finished_at=utc_now(),
                summary=summary,
            ),
        )
    if compile_result.outcome == "launch_failed":
        status, summary = input_stable_status(
            bundle,
            "blocked",
            {
                "phase": "compile",
                "launch_failed": True,
                "launch_error": compile_result.error_type,
                "compile_manifest": bundle.option_summary(),
            },
        )
        return write_evidence(
            current_run,
            base_evidence(
                kind="simulation",
                status=status,
                tool_name=tool_name,
                tool_version_value=tool_version_value,
                bundle=bundle,
                commands=[compile_command],
                artifacts=[compile_stdout_path.as_posix(), compile_stderr_path.as_posix()],
                started_at=started_at,
                finished_at=utc_now(),
                summary=summary,
            ),
        )

    artifacts = [compile_stdout_path.as_posix(), compile_stderr_path.as_posix()]
    compile_returncode = compile_result.completed_returncode()
    if compile_returncode != 0:
        summary = {
            "phase": "compile",
            "compile_returncode": compile_returncode,
            "compile_manifest": bundle.option_summary(),
        }
        status, summary = input_stable_status(bundle, "fail", summary)
        return write_evidence(
            current_run,
            base_evidence(
                kind="simulation",
                status=status,
                tool_name=tool_name,
                tool_version_value=tool_version_value,
                bundle=bundle,
                commands=[compile_command],
                artifacts=artifacts,
                started_at=started_at,
                finished_at=utc_now(),
                summary=summary,
            ),
        )
    if not executable_path.is_file():
        summary = {
            "phase": "compile",
            "compile_returncode": compile_returncode,
            "missing_compiled_artifact": True,
            "compile_manifest": bundle.option_summary(),
        }
        status, summary = input_stable_status(bundle, "blocked", summary)
        return write_evidence(
            current_run,
            base_evidence(
                kind="simulation",
                status=status,
                tool_name=tool_name,
                tool_version_value=tool_version_value,
                bundle=bundle,
                commands=[compile_command],
                artifacts=artifacts,
                started_at=started_at,
                finished_at=utc_now(),
                summary=summary,
            ),
        )

    run_result = run_tool_command(run_command, timeout_seconds=timeout_seconds)
    if run_result.outcome == "completed":
        run_returncode = run_result.completed_returncode()
        status = "pass" if run_returncode == 0 else "fail"
        summary = {
            "phase": "run",
            "compile_returncode": compile_returncode,
            "run_returncode": run_returncode,
            "compile_manifest": bundle.option_summary(),
        }
    elif run_result.outcome == "timeout":
        status = "timeout"
        summary = {
            "phase": "run",
            "compile_returncode": compile_returncode,
            "timeout_seconds": timeout_seconds,
            "compile_manifest": bundle.option_summary(),
        }
    else:
        status = "blocked"
        summary = {
            "phase": "run",
            "compile_returncode": compile_returncode,
            "launch_failed": True,
            "launch_error": run_result.error_type,
            "compile_manifest": bundle.option_summary(),
        }
    run_stdout_path = current_run / "run.stdout.log"
    run_stderr_path = current_run / "run.stderr.log"
    run_stdout_path.write_text(run_result.stdout, encoding="utf-8")
    run_stderr_path.write_text(run_result.stderr, encoding="utf-8")
    artifacts.extend([executable_path.as_posix(), run_stdout_path.as_posix(), run_stderr_path.as_posix()])
    status, summary = input_stable_status(bundle, status, summary)
    return write_evidence(
        current_run,
        base_evidence(
            kind="simulation",
            status=status,
            tool_name=tool_name,
            tool_version_value=tool_version_value,
            bundle=bundle,
            commands=[compile_command, run_command],
            artifacts=artifacts,
            started_at=started_at,
            finished_at=utc_now(),
            summary=summary,
        ),
    )
