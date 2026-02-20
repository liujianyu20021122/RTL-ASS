"""OpenSTA timing evidence adapter."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from rtl_ass.errors import RtlAssError
from rtl_ass.evidence_common import (
    StaInputBundle,
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


def run_opensta(
    *,
    netlist: str | Path,
    liberty: str | Path,
    constraints: str | Path,
    top: str,
    artifact_root: str | Path,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    bundle = StaInputBundle.create(netlist=netlist, liberty=liberty, constraints=constraints, top=top)
    validate_timeout(timeout_seconds)
    executable = shutil.which("sta") or shutil.which("opensta")
    if executable is None:
        return unavailable_evidence(
            kind="sta",
            tool_name="opensta",
            bundle=bundle,
            summary={"input_roles": list(bundle.roles)},
        )
    version = tool_version(executable, ["-version"])

    current_run = run_directory(artifact_root, "sta", "opensta")
    script_path = current_run / "timing.tcl"
    stdout_path = current_run / "stdout.log"
    stderr_path = current_run / "stderr.log"
    report_paths = {
        "clocks": current_run / "clocks.rpt",
        "clock_count": current_run / "clock-count.rpt",
        "setup_slack": current_run / "setup-slack.rpt",
        "hold_slack": current_run / "hold-slack.rpt",
        "setup_tns": current_run / "setup-tns.rpt",
        "hold_tns": current_run / "hold-tns.rpt",
        "checks": current_run / "checks.rpt",
        "setup_paths": current_run / "setup-paths.rpt",
        "hold_paths": current_run / "hold-paths.rpt",
    }
    netlist_path, liberty_path, constraints_path = bundle.files
    script = "\n".join(
        [
            f"read_liberty {_tcl_quote(liberty_path)}",
            f"read_verilog {_tcl_quote(netlist_path)}",
            f"link_design {bundle.top}",
            f"read_sdc {_tcl_quote(constraints_path)}",
            f"report_clock_properties [all_clocks] > {_tcl_quote(report_paths['clocks'])}",
            f"set rtl_ass_clock_file [open {_tcl_quote(report_paths['clock_count'])} w]",
            "puts $rtl_ass_clock_file [llength [all_clocks]]",
            "close $rtl_ass_clock_file",
            f"report_worst_slack -max -digits 9 > {_tcl_quote(report_paths['setup_slack'])}",
            f"report_worst_slack -min -digits 9 > {_tcl_quote(report_paths['hold_slack'])}",
            f"report_tns -max -digits 9 > {_tcl_quote(report_paths['setup_tns'])}",
            f"report_tns -min -digits 9 > {_tcl_quote(report_paths['hold_tns'])}",
            f"check_setup -verbose -unconstrained_endpoints > {_tcl_quote(report_paths['checks'])}",
            f"report_checks -path_delay max -format full_clock_expanded -digits 9 > {_tcl_quote(report_paths['setup_paths'])}",
            f"report_checks -path_delay min -format full_clock_expanded -digits 9 > {_tcl_quote(report_paths['hold_paths'])}",
            "exit",
            "",
        ]
    )
    script_path.write_text(script, encoding="utf-8")
    command = [executable, "-no_splash", "-exit", str(script_path)]
    started_at = utc_now()
    result = run_tool_command(command, timeout_seconds=timeout_seconds, cwd=current_run)
    summary: dict[str, Any] = {"input_roles": list(bundle.roles)}
    if result.outcome == "timeout":
        status = "timeout"
        summary["timeout_seconds"] = timeout_seconds
    elif result.outcome == "launch_failed":
        status = "blocked"
        summary.update({"launch_failed": True, "launch_error": result.error_type})
    else:
        returncode = result.completed_returncode()
        status = "pass" if returncode == 0 else "fail"
        summary["returncode"] = returncode
    stdout = result.stdout
    stderr = result.stderr
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")

    if status == "pass":
        missing = [name for name, path in report_paths.items() if not path.is_file()]
        if missing:
            status = "blocked"
            summary["missing_reports"] = missing
        else:
            try:
                check_report = report_paths["checks"].read_text(encoding="utf-8")
                unconstrained = _parse_unconstrained_endpoint_count(check_report)
                clock_count = _parse_nonnegative_integer(report_paths["clock_count"], "clock count")
                setup_slack = _parse_opensta_metric(report_paths["setup_slack"], "worst slack max")
                hold_slack = _parse_opensta_metric(report_paths["hold_slack"], "worst slack min")
                setup_tns = _parse_opensta_metric(report_paths["setup_tns"], "tns max")
                hold_tns = _parse_opensta_metric(report_paths["hold_tns"], "tns min")
            except (RtlAssError, UnicodeDecodeError) as exc:
                status = "blocked"
                summary["report_parse_error"] = str(exc)
            else:
                timing_met = (
                    setup_slack >= 0.0 and hold_slack >= 0.0
                    if setup_slack is not None and hold_slack is not None
                    else None
                )
                summary.update(
                    {
                        "setup_worst_slack": setup_slack,
                        "hold_worst_slack": hold_slack,
                        "setup_total_negative_slack": setup_tns,
                        "hold_total_negative_slack": hold_tns,
                        "unconstrained_endpoint_count": unconstrained,
                        "clock_count": clock_count,
                        "timing_met": timing_met,
                    }
                )
                if clock_count == 0 or unconstrained > 0 or timing_met is None:
                    status = "blocked"
                elif not timing_met:
                    status = "fail"

    status, summary = input_stable_status(bundle, status, summary)
    artifacts = [script_path, stdout_path, stderr_path]
    artifacts.extend(path for path in report_paths.values() if path.is_file())
    evidence = base_evidence(
        kind="sta",
        status=status,
        tool_name="opensta",
        tool_version_value=version,
        bundle=bundle,
        commands=[command],
        artifacts=[path.as_posix() for path in artifacts],
        started_at=started_at,
        finished_at=utc_now(),
        summary=summary,
    )
    return write_evidence(current_run, evidence)


def _tcl_quote(path: Path) -> str:
    value = str(path)
    if "\n" in value or "\r" in value:
        raise RtlAssError("invalid_sta_path", "OpenSTA input paths must not contain line breaks")
    escaped = value.replace("\\", "\\\\")
    for character in ('"', "$", "[", "]"):
        escaped = escaped.replace(character, "\\" + character)
    return f'"{escaped}"'


def _parse_opensta_metric(path: Path, label: str) -> float | None:
    report = path.read_text(encoding="utf-8").strip()
    match = re.fullmatch(
        rf"{re.escape(label)}\s+([-+]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?|INF))",
        report,
        flags=re.IGNORECASE,
    )
    if match is None:
        raise RtlAssError(
            "invalid_sta_report",
            "OpenSTA metric report has an unexpected format",
            {"path": str(path), "label": label, "content": report[:200]},
        )
    value = match.group(1)
    return None if value.upper().endswith("INF") else float(value)


def _parse_unconstrained_endpoint_count(report: str) -> int:
    if not report.strip() or re.search(r"\bno\s+unconstrained endpoints?\b", report, flags=re.IGNORECASE):
        return 0
    matches = re.findall(r"(?:there (?:is|are)\s+)?(\d+)\s+unconstrained endpoints?", report, flags=re.IGNORECASE)
    if not matches:
        raise RtlAssError(
            "invalid_sta_report",
            "OpenSTA unconstrained-endpoint report has an unexpected format",
            {"content": report[:200]},
        )
    return max(int(value) for value in matches)


def _parse_nonnegative_integer(path: Path, label: str) -> int:
    report = path.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+", report):
        raise RtlAssError(
            "invalid_sta_report",
            "OpenSTA integer report has an unexpected format",
            {"path": str(path), "label": label, "content": report[:200]},
        )
    return int(report)
