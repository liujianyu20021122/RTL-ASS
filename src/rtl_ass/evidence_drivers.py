"""Native SymbiYosys and EQY evidence adapters."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from rtl_ass.compile_manifest import CompileInput, CompileManifest, yosys_parameter_commands, yosys_read_command
from rtl_ass.errors import RtlAssError
from rtl_ass.evidence_common import (
    EquivalenceInputBundle,
    FormalInputBundle,
    ToolVersionProbe,
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

_SOLVERS = frozenset({"bitwuzla", "boolector", "cvc5", "yices", "z3"})
_MAX_DRIVER_TRACES = 64
_MAX_DRIVER_TRACE_BYTES = 256 * 1024 * 1024


def run_symbiyosys_formal(
    sources: CompileInput,
    *,
    top: str | None = None,
    depth: int,
    initialization: str,
    artifact_root: str | Path,
    timeout_seconds: int = 120,
    solver: str = "z3",
) -> dict[str, Any]:
    bundle = FormalInputBundle.create(sources, top=top, depth=depth, initialization=initialization)
    validate_timeout(timeout_seconds)
    _validate_solver(solver)
    executable = shutil.which("sby")
    if executable is None:
        return unavailable_evidence(
            kind="formal",
            tool_name="symbiyosys",
            bundle=bundle,
            summary={"depth": depth, "initialization": initialization, "solver": solver, "mode": "bounded"},
        )

    current_run = run_directory(artifact_root, "formal", "symbiyosys")
    config_path = current_run / "formal.sby"
    output_directory = current_run / "job"
    script = [
        yosys_read_command(bundle.source_bundle, formal=True),
        *yosys_parameter_commands(bundle.source_bundle),
        f"prep -top {bundle.top}",
    ]
    if bundle.initialization == "zero":
        script.append("setundef -init -zero")
    # Yosys 0.67 lowers SystemVerilog assertions to $check cells during
    # ``prep``; older releases retain $assert. Require at least one of either
    # representation so an empty proof scope can never pass silently.
    script.append("select -assert-min 1 t:$assert t:$check")
    config_path.write_text(
        "\n".join(
            [
                "[options]",
                "mode bmc",
                f"depth {bundle.depth}",
                f"timeout {timeout_seconds}",
                "expect pass,fail,unknown,error,timeout",
                "",
                "[engines]",
                f"smtbmc {solver}",
                "",
                "[script]",
                *script,
                "",
            ]
        ),
        encoding="utf-8",
    )
    command = [executable, "-f", "-d", str(output_directory), str(config_path)]
    return _run_sby(
        command=command,
        current_run=current_run,
        output_directory=output_directory,
        config_path=config_path,
        bundle=bundle,
        version=tool_version(executable, ["--version"]),
        solver=solver,
        timeout_seconds=timeout_seconds,
    )


def run_eqy_equivalence(
    *,
    reference_sources: CompileInput,
    implementation_sources: CompileInput,
    reference_top: str | None = None,
    implementation_top: str | None = None,
    depth: int,
    initialization: str = "none",
    input_domain: str = "defined",
    artifact_root: str | Path,
    timeout_seconds: int = 120,
    solver: str = "z3",
) -> dict[str, Any]:
    bundle = EquivalenceInputBundle.create(
        reference_sources,
        implementation_sources,
        reference_top=reference_top,
        implementation_top=implementation_top,
        depth=depth,
        input_domain=input_domain,
        initialization=initialization,
    )
    validate_timeout(timeout_seconds)
    _validate_solver(solver)
    executable = shutil.which("eqy")
    if executable is None:
        return unavailable_evidence(
            kind="equivalence",
            tool_name="eqy",
            bundle=bundle,
            summary={
                "depth": depth,
                "initialization": initialization,
                "input_domain": input_domain,
                "solver": solver,
                "strategy": "sby",
            },
        )

    current_run = run_directory(artifact_root, "equivalence", "eqy")
    config_path = current_run / "equivalence.eqy"
    output_directory = current_run / "job"
    gold = _eqy_design_script(bundle.reference, canonical_top="rtl_ass_equiv_top", zero=initialization == "zero")
    gate = _eqy_design_script(bundle.implementation, canonical_top="rtl_ass_equiv_top", zero=initialization == "zero")
    config_path.write_text(
        "\n".join(
            [
                "[gold]",
                *gold,
                "",
                "[gate]",
                *gate,
                "",
                "[strategy rtl_ass]",
                "use sby",
                f"engine smtbmc {solver}",
                f"depth {depth}",
                f"timeout {timeout_seconds}",
                f"xprop {'on' if input_domain == 'undefined' else 'off'}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    command = [executable, "-f", "-d", str(output_directory), str(config_path)]
    return _run_eqy(
        command=command,
        current_run=current_run,
        output_directory=output_directory,
        config_path=config_path,
        bundle=bundle,
        version=tool_version(executable, ["--version"]),
        solver=solver,
        timeout_seconds=timeout_seconds,
    )


def _eqy_design_script(manifest: CompileManifest, *, canonical_top: str, zero: bool) -> list[str]:
    script = [
        yosys_read_command(manifest),
        *yosys_parameter_commands(manifest),
        f"prep -top {manifest.top}",
    ]
    if zero:
        script.append("setundef -init -zero")
    script.append(f"rename -top {canonical_top}")
    return script


def _run_sby(
    *,
    command: list[str],
    current_run: Path,
    output_directory: Path,
    config_path: Path,
    bundle: FormalInputBundle,
    version: str | ToolVersionProbe,
    solver: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    returncode, stdout, stderr, timed_out, started_at = _run_driver(command, timeout_seconds)
    stdout_path, stderr_path = _write_driver_logs(current_run, stdout, stderr)
    status_path = output_directory / "status"
    marker = _read_marker(status_path, allowed={"PASS", "FAIL", "UNKNOWN", "ERROR", "TIMEOUT"})
    traces = _driver_traces(output_directory)
    if timed_out or marker == "TIMEOUT":
        status = "timeout"
    elif marker == "PASS" and returncode == 0:
        status = "pass"
    elif marker == "FAIL" and traces:
        status = "fail"
    else:
        status = "blocked"
    summary: dict[str, Any] = {
        "returncode": returncode,
        "driver_status": marker,
        "depth": bundle.depth,
        "initialization": bundle.initialization,
        "solver": solver,
        "mode": "bounded",
        "compile_manifest": bundle.source_bundle.option_summary(),
        "counterexample_count": len(traces),
    }
    if timed_out:
        summary["timeout_seconds"] = timeout_seconds
    status, summary = input_stable_status(bundle, status, summary)
    artifacts = [config_path, stdout_path, stderr_path]
    if status_path.is_file() and not status_path.is_symlink():
        artifacts.append(status_path)
    artifacts.extend(traces)
    return write_evidence(
        current_run,
        base_evidence(
            kind="formal",
            status=status,
            tool_name="symbiyosys",
            tool_version_value=version,
            bundle=bundle,
            commands=[command],
            artifacts=[path.as_posix() for path in artifacts],
            started_at=started_at,
            finished_at=utc_now(),
            summary=summary,
        ),
    )


def _run_eqy(
    *,
    command: list[str],
    current_run: Path,
    output_directory: Path,
    config_path: Path,
    bundle: EquivalenceInputBundle,
    version: str | ToolVersionProbe,
    solver: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    returncode, stdout, stderr, timed_out, started_at = _run_driver(command, timeout_seconds)
    stdout_path, stderr_path = _write_driver_logs(current_run, stdout, stderr)
    pass_marker = output_directory / "PASS"
    fail_marker = output_directory / "FAIL"
    traces = _driver_traces(output_directory)
    if timed_out:
        status = "timeout"
        marker = "TIMEOUT"
    elif pass_marker.is_file() and not pass_marker.is_symlink() and not fail_marker.exists() and returncode == 0:
        status = "pass"
        marker = "PASS"
    elif fail_marker.is_file() and not fail_marker.is_symlink() and not pass_marker.exists():
        status = "fail" if traces else "blocked"
        marker = "FAIL"
    else:
        status = "blocked"
        marker = "INVALID_OR_MISSING"
    summary: dict[str, Any] = {
        "returncode": returncode,
        "driver_status": marker,
        "depth": bundle.depth,
        "initialization": bundle.initialization,
        "input_domain": bundle.input_domain,
        "solver": solver,
        "strategy": "sby",
        "proof_mode": "induction",
        "counterexample_count": len(traces),
        "reference_compile_manifest": bundle.reference.option_summary(),
        "implementation_compile_manifest": bundle.implementation.option_summary(),
    }
    if timed_out:
        summary["timeout_seconds"] = timeout_seconds
    status, summary = input_stable_status(bundle, status, summary)
    artifacts = [config_path, stdout_path, stderr_path]
    for path in (pass_marker, fail_marker, output_directory / "logfile.txt"):
        if path.is_file() and not path.is_symlink():
            artifacts.append(path)
    artifacts.extend(traces)
    return write_evidence(
        current_run,
        base_evidence(
            kind="equivalence",
            status=status,
            tool_name="eqy",
            tool_version_value=version,
            bundle=bundle,
            commands=[command],
            artifacts=[path.as_posix() for path in artifacts],
            started_at=started_at,
            finished_at=utc_now(),
            summary=summary,
        ),
    )


def _run_driver(command: list[str], timeout_seconds: int) -> tuple[int | None, str, str, bool, str]:
    started_at = utc_now()
    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
        )
        return result.returncode, result.stdout, result.stderr, False, started_at
    except subprocess.TimeoutExpired as exc:
        return None, timeout_text(exc.stdout), timeout_text(exc.stderr), True, started_at


def _write_driver_logs(current_run: Path, stdout: str, stderr: str) -> tuple[Path, Path]:
    stdout_path = current_run / "stdout.log"
    stderr_path = current_run / "stderr.log"
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    return stdout_path, stderr_path


def _read_marker(path: Path, *, allowed: set[str]) -> str:
    if not path.is_file() or path.is_symlink():
        return "INVALID_OR_MISSING"
    try:
        marker = path.read_text(encoding="utf-8").strip().split()[0].upper()
    except (IndexError, UnicodeDecodeError):
        return "INVALID_OR_MISSING"
    return marker if marker in allowed else "INVALID_OR_MISSING"


def _driver_traces(root: Path) -> list[Path]:
    if not root.is_dir() or root.is_symlink():
        return []
    traces: list[Path] = []
    total_bytes = 0
    for path in sorted(root.rglob("*.vcd")):
        if path.is_symlink() or not path.is_file():
            continue
        traces.append(path)
        total_bytes += path.stat().st_size
        if len(traces) > _MAX_DRIVER_TRACES or total_bytes > _MAX_DRIVER_TRACE_BYTES:
            raise RtlAssError(
                "driver_trace_limit_exceeded",
                "formal driver traces exceed the audited artifact limits",
                {"max_files": _MAX_DRIVER_TRACES, "max_bytes": _MAX_DRIVER_TRACE_BYTES},
            )
    return traces


def _validate_solver(solver: str) -> None:
    if solver not in _SOLVERS:
        raise RtlAssError("invalid_formal_solver", "unsupported formal solver", {"solver": solver})
