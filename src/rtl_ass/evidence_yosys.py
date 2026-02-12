"""Yosys synthesis evidence adapters."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Sequence

from rtl_ass.evidence_common import (
    EquivalenceInputBundle,
    FormalInputBundle,
    SourceBundle,
    base_evidence,
    input_stable_status,
    run_directory,
    timeout_text,
    tool_version,
    unavailable_evidence,
    validate_timeout,
    write_evidence,
    yosys_quote,
)
from rtl_ass.integrity import parse_json, utc_now


def run_yosys_synthesis(
    sources: Sequence[str | Path],
    *,
    top: str,
    artifact_root: str | Path,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    bundle = SourceBundle.create(sources, top)
    validate_timeout(timeout_seconds)
    executable = shutil.which("yosys")
    if executable is None:
        return unavailable_evidence(kind="synthesis", tool_name="yosys", bundle=bundle)
    version = tool_version(executable, ["-V"])

    current_run = run_directory(artifact_root, "synthesis", "yosys")
    script_path = current_run / "synthesis.ys"
    log_path = current_run / "yosys.log"
    stats_path = current_run / "stats.json"
    netlist_path = current_run / "netlist.json"
    read_commands = [f"read_verilog -sv {yosys_quote(source)}" for source in bundle.sources]
    script = "\n".join(
        [
            *read_commands,
            f"hierarchy -check -top {bundle.top}",
            "proc",
            "opt",
            "check",
            f"synth -top {bundle.top}",
            "check",
            # These are fixed filenames inside cwd.  Yosys 0.33's tee pass
            # cannot reliably create a quoted absolute output path, while
            # newer releases accept it.  Relative names are portable across
            # both versions and cannot be influenced by user input.
            "tee -o stats.json stat -json",
            "write_json netlist.json",
            "",
        ]
    )
    script_path.write_text(script, encoding="utf-8")
    stdout_path = current_run / "stdout.log"
    stderr_path = current_run / "stderr.log"
    command = [executable, "-q", "-l", str(log_path), "-s", str(script_path)]
    started_at = utc_now()
    try:
        result = subprocess.run(
            command,
            check=False,
            cwd=current_run,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
        )
        status = "pass" if result.returncode == 0 else "fail"
        stdout = result.stdout
        stderr = result.stderr
        summary: dict[str, Any] = {"returncode": result.returncode}
    except subprocess.TimeoutExpired as exc:
        status = "timeout"
        stdout = timeout_text(exc.stdout)
        stderr = timeout_text(exc.stderr)
        summary = {"timeout_seconds": timeout_seconds}
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")

    if status == "fail":
        combined = _combined_tool_output(stdout, stderr, log_path)
        summary["tool_error"] = _last_nonempty_line(combined)

    if status == "pass":
        if not stats_path.is_file() or not netlist_path.is_file():
            status = "blocked"
            summary["missing_required_artifact"] = True
        else:
            try:
                stats = parse_json(stats_path.read_text(encoding="utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                status = "blocked"
                summary["stats_parse_error"] = str(exc)
            else:
                summary["statistics"] = stats
    status, summary = input_stable_status(bundle, status, summary)
    artifacts = [script_path, log_path, stdout_path, stderr_path]
    artifacts.extend(path for path in (stats_path, netlist_path) if path.is_file())
    evidence = base_evidence(
        kind="synthesis",
        status=status,
        tool_name="yosys",
        tool_version_value=version,
        bundle=bundle,
        commands=[command],
        artifacts=[path.as_posix() for path in artifacts],
        started_at=started_at,
        finished_at=utc_now(),
        summary=summary,
    )
    return write_evidence(current_run, evidence)


def run_yosys_formal(
    sources: Sequence[str | Path],
    *,
    top: str,
    depth: int,
    initialization: str,
    artifact_root: str | Path,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    bundle = FormalInputBundle.create(
        sources,
        top=top,
        depth=depth,
        initialization=initialization,
    )
    validate_timeout(timeout_seconds)
    executable = shutil.which("yosys")
    if executable is None:
        return unavailable_evidence(
            kind="formal",
            tool_name="yosys-sat",
            bundle=bundle,
            summary={"depth": depth, "initialization": initialization, "mode": "bounded"},
        )
    version = tool_version(executable, ["-V"])
    current_run = run_directory(artifact_root, "formal", "yosys-sat")
    script_path = current_run / "formal.ys"
    log_path = current_run / "yosys.log"
    stdout_path = current_run / "stdout.log"
    stderr_path = current_run / "stderr.log"
    counterexample_path = current_run / "counterexample.vcd"
    initialization_option = "-set-init-zero" if initialization == "zero" else "-set-init-def"
    script_path.write_text(
        "\n".join(
            [
                *(f"read_verilog -formal -sv {yosys_quote(source)}" for source in bundle.sources),
                f"hierarchy -check -top {bundle.top}",
                f"prep -top {bundle.top}",
                "flatten",
                "async2sync",
                "dffunmap",
                "opt_clean",
                "select -assert-min 1 t:$assert",
                f"select -module {bundle.top}",
                (
                    f"sat -verify -prove-asserts -set-assumes -set-def-inputs -enable_undef -seq {bundle.depth} "
                    f"{initialization_option} -show-ports -dump_vcd {yosys_quote(counterexample_path)}"
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )
    command = [executable, "-q", "-l", str(log_path), "-s", str(script_path)]
    started_at = utc_now()
    returncode, stdout, stderr, timed_out = _run_yosys(command, current_run, timeout_seconds)
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    combined = _combined_tool_output(stdout, stderr, log_path)
    if timed_out:
        status = "timeout"
    elif returncode == 0:
        status = "pass"
    elif "proof did fail" in combined.lower():
        status = "fail"
    else:
        status = "blocked"
    summary: dict[str, Any] = {
        "returncode": returncode,
        "depth": bundle.depth,
        "initialization": bundle.initialization,
        "mode": "bounded",
        "assumptions_enforced": True,
        "defined_inputs": True,
    }
    if timed_out:
        summary["timeout_seconds"] = timeout_seconds
    elif status == "blocked":
        summary["tool_error"] = _last_nonempty_line(combined)
    status, summary = input_stable_status(bundle, status, summary)
    summary["proof_passed"] = _three_state_result(status)
    artifacts = [script_path, log_path, stdout_path, stderr_path]
    if counterexample_path.is_file():
        artifacts.append(counterexample_path)
    evidence = base_evidence(
        kind="formal",
        status=status,
        tool_name="yosys-sat",
        tool_version_value=version,
        bundle=bundle,
        commands=[command],
        artifacts=[path.as_posix() for path in artifacts],
        started_at=started_at,
        finished_at=utc_now(),
        summary=summary,
    )
    return write_evidence(current_run, evidence)


def run_yosys_equivalence(
    *,
    reference_sources: Sequence[str | Path],
    implementation_sources: Sequence[str | Path],
    reference_top: str,
    implementation_top: str,
    depth: int,
    artifact_root: str | Path,
    timeout_seconds: int = 120,
    input_domain: str = "defined",
) -> dict[str, Any]:
    bundle = EquivalenceInputBundle.create(
        reference_sources,
        implementation_sources,
        reference_top=reference_top,
        implementation_top=implementation_top,
        depth=depth,
        input_domain=input_domain,
    )
    validate_timeout(timeout_seconds)
    executable = shutil.which("yosys")
    summary_base = {
        "reference_top": bundle.reference.top,
        "implementation_top": bundle.implementation.top,
        "depth": bundle.depth,
        "mode": "combinational" if depth == 1 else "bounded-sequential",
        "input_domain": bundle.input_domain,
    }
    if executable is None:
        return unavailable_evidence(
            kind="equivalence",
            tool_name="yosys-equiv",
            bundle=bundle,
            summary=summary_base,
        )
    version = tool_version(executable, ["-V"])
    current_run = run_directory(artifact_root, "equivalence", "yosys-equiv")
    script_path = current_run / "equivalence.ys"
    log_path = current_run / "yosys.log"
    stdout_path = current_run / "stdout.log"
    stderr_path = current_run / "stderr.log"
    script_path.write_text(
        "\n".join(
            [
                *(f"read_verilog -sv {yosys_quote(source)}" for source in bundle.reference.sources),
                f"hierarchy -check -top {bundle.reference.top}",
                "proc",
                "memory",
                "opt",
                "flatten",
                "rename -top rtl_ass_gold",
                "design -stash rtl_ass_reference",
                "design -reset-vlog",
                *(f"read_verilog -sv {yosys_quote(source)}" for source in bundle.implementation.sources),
                f"hierarchy -check -top {bundle.implementation.top}",
                "proc",
                "memory",
                "opt",
                "flatten",
                "rename -top rtl_ass_gate",
                "design -stash rtl_ass_implementation",
                "design -copy-from rtl_ass_reference rtl_ass_gold",
                "design -copy-from rtl_ass_implementation rtl_ass_gate",
                "equiv_make rtl_ass_gold rtl_ass_gate rtl_ass_equiv",
                "hierarchy -check -top rtl_ass_equiv",
                f"equiv_simple {'-undef ' if bundle.input_domain == 'undefined' else ''}-seq {bundle.depth}",
                "equiv_status -assert",
                "",
            ]
        ),
        encoding="utf-8",
    )
    command = [executable, "-q", "-l", str(log_path), "-s", str(script_path)]
    started_at = utc_now()
    returncode, stdout, stderr, timed_out = _run_yosys(command, current_run, timeout_seconds)
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    combined = _combined_tool_output(stdout, stderr, log_path)
    if timed_out:
        status = "timeout"
    elif returncode == 0:
        status = "pass"
    elif "unproven $equiv" in combined.lower():
        status = "fail"
    else:
        status = "blocked"
    summary = {
        **summary_base,
        "returncode": returncode,
    }
    if timed_out:
        summary["timeout_seconds"] = timeout_seconds
    elif status == "blocked":
        summary["tool_error"] = _last_nonempty_line(combined)
    status, summary = input_stable_status(bundle, status, summary)
    summary["equivalent"] = _three_state_result(status)
    evidence = base_evidence(
        kind="equivalence",
        status=status,
        tool_name="yosys-equiv",
        tool_version_value=version,
        bundle=bundle,
        commands=[command],
        artifacts=[path.as_posix() for path in (script_path, log_path, stdout_path, stderr_path)],
        started_at=started_at,
        finished_at=utc_now(),
        summary=summary,
    )
    return write_evidence(current_run, evidence)


def _run_yosys(
    command: list[str],
    current_run: Path,
    timeout_seconds: int,
) -> tuple[int | None, str, str, bool]:
    try:
        result = subprocess.run(
            command,
            check=False,
            cwd=current_run,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
        )
        return result.returncode, result.stdout, result.stderr, False
    except subprocess.TimeoutExpired as exc:
        return None, timeout_text(exc.stdout), timeout_text(exc.stderr), True


def _combined_tool_output(stdout: str, stderr: str, log_path: Path) -> str:
    log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
    return "\n".join((stdout, stderr, log))


def _last_nonempty_line(value: str) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    return lines[-1][:500] if lines else "unknown Yosys failure"


def _three_state_result(status: str) -> bool | None:
    if status == "pass":
        return True
    if status == "fail":
        return False
    return None
