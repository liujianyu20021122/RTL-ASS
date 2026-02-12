"""Bounded, machine-readable VCD queries for Codex."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from rtl_ass.errors import RtlAssError
from rtl_ass.integrity import hash_file


@dataclass(frozen=True, slots=True)
class VcdSignal:
    identifier: str
    width: int
    variable_type: str
    name: str


def _matches_signal(name: str, pattern: str) -> bool:
    if fnmatch.fnmatchcase(name, pattern):
        return True
    return "." not in pattern and fnmatch.fnmatchcase(name.rsplit(".", 1)[-1], pattern)


def _parse_var(directive: str, scopes: list[str]) -> VcdSignal:
    tokens = directive.split()
    if len(tokens) < 6 or tokens[0] != "$var" or tokens[-1] != "$end":
        raise RtlAssError("invalid_vcd", "malformed VCD variable declaration", {"directive": directive})
    try:
        width = int(tokens[2])
    except ValueError as exc:
        raise RtlAssError("invalid_vcd", "VCD variable width must be an integer", {"directive": directive}) from exc
    reference = "".join(tokens[4:-1])
    name = ".".join([*scopes, reference])
    return VcdSignal(identifier=tokens[3], width=width, variable_type=tokens[1], name=name)


def _selected_names(signals: Iterable[VcdSignal], patterns: tuple[str, ...]) -> dict[str, list[VcdSignal]]:
    selected: dict[str, list[VcdSignal]] = {}
    for signal in signals:
        if any(_matches_signal(signal.name, pattern) for pattern in patterns):
            selected.setdefault(signal.identifier, []).append(signal)
    if not selected:
        raise RtlAssError(
            "wave_signal_not_found", "no VCD signal matched the requested patterns", {"patterns": patterns}
        )
    return selected


def query_vcd(
    path: str | Path,
    *,
    patterns: Iterable[str],
    start_time: int = 0,
    end_time: int | None = None,
    max_events: int = 1000,
) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise RtlAssError("waveform_not_found", "VCD file does not exist", {"path": str(source)})
    pattern_values = tuple(patterns)
    if not pattern_values or any(not isinstance(pattern, str) or not pattern for pattern in pattern_values):
        raise RtlAssError("wave_signal_required", "at least one signal pattern is required")
    if (
        isinstance(start_time, bool)
        or not isinstance(start_time, int)
        or start_time < 0
        or (
            end_time is not None
            and (isinstance(end_time, bool) or not isinstance(end_time, int) or end_time < start_time)
        )
    ):
        raise RtlAssError("invalid_wave_window", "waveform time window is invalid")
    if isinstance(max_events, bool) or not isinstance(max_events, int) or max_events < 1 or max_events > 100_000:
        raise RtlAssError("invalid_event_limit", "max_events must be between 1 and 100000")

    content_hash = hash_file(source)
    scopes: list[str] = []
    declarations: list[VcdSignal] = []
    timescale = "unknown"
    in_header = True
    pending_directive = ""
    selected: dict[str, list[VcdSignal]] | None = None
    current_time = 0
    events: list[dict[str, Any]] = []
    truncated = False

    try:
        with source.open("r", encoding="utf-8", errors="strict") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                if in_header:
                    pending_directive = f"{pending_directive} {line}".strip()
                    if "$end" not in pending_directive:
                        continue
                    directive = pending_directive
                    pending_directive = ""
                    tokens = directive.split()
                    if directive.startswith("$scope"):
                        if len(tokens) < 4:
                            raise RtlAssError("invalid_vcd", "malformed VCD scope", {"line": line_number})
                        scopes.append(tokens[2])
                    elif directive.startswith("$upscope"):
                        if not scopes:
                            raise RtlAssError("invalid_vcd", "VCD upscope has no matching scope", {"line": line_number})
                        scopes.pop()
                    elif directive.startswith("$var"):
                        declarations.append(_parse_var(directive, scopes))
                    elif directive.startswith("$timescale"):
                        timescale = "".join(tokens[1:-1])
                    elif directive.startswith("$enddefinitions"):
                        in_header = False
                        selected = _selected_names(declarations, pattern_values)
                    continue

                if line.startswith("#"):
                    try:
                        current_time = int(line[1:])
                    except ValueError as exc:
                        raise RtlAssError(
                            "invalid_vcd", "VCD timestamp is not an integer", {"line": line_number}
                        ) from exc
                    if end_time is not None and current_time > end_time:
                        break
                    continue
                if line.startswith("$"):
                    continue
                if current_time < start_time:
                    continue
                if selected is None:
                    raise RtlAssError("invalid_vcd", "VCD parser entered data state without declarations")
                value, identifier = _parse_value_change(line, line_number)
                for signal in selected.get(identifier, []):
                    events.append({"time": current_time, "signal": signal.name, "value": value})
                    if len(events) >= max_events:
                        truncated = True
                        break
                if truncated:
                    break
    except UnicodeDecodeError as exc:
        raise RtlAssError(
            "invalid_vcd_encoding",
            "VCD must be valid UTF-8/ASCII text",
            {"path": str(source), "offset": exc.start},
        ) from exc

    if in_header:
        raise RtlAssError("invalid_vcd", "VCD enddefinitions marker was not found")
    if selected is None:
        raise RtlAssError("invalid_vcd", "VCD declarations were not finalized")
    final_hash = hash_file(source)
    if final_hash != content_hash:
        raise RtlAssError(
            "waveform_changed",
            "VCD changed while it was being queried",
            {"path": str(source), "initial_hash": content_hash, "final_hash": final_hash},
        )
    selected_signals = sorted(
        {
            signal.name: {
                "name": signal.name,
                "identifier": signal.identifier,
                "width": signal.width,
                "variable_type": signal.variable_type,
            }
            for signal_list in selected.values()
            for signal in signal_list
        }.values(),
        key=lambda item: str(item["name"]),
    )
    return {
        "schema_version": "1.0",
        "kind": "vcd-query",
        "status": "truncated" if truncated else "complete",
        "waveform": source.as_posix(),
        "waveform_hash": content_hash,
        "timescale": timescale,
        "window": {"start": start_time, "end": end_time},
        "patterns": list(pattern_values),
        "selected_signals": selected_signals,
        "event_count": len(events),
        "events": events,
    }


def first_divergence_vcd(
    path: str | Path,
    *,
    expected: str,
    actual: str,
    start_time: int = 0,
    end_time: int | None = None,
    max_events: int = 100_000,
) -> dict[str, Any]:
    query = query_vcd(
        path,
        patterns=(expected, actual),
        start_time=start_time,
        end_time=end_time,
        max_events=max_events,
    )
    return build_first_divergence(
        query,
        expected=expected,
        actual=actual,
        kind="vcd-first-divergence",
    )


def build_first_divergence(
    query: dict[str, Any],
    *,
    expected: str,
    actual: str,
    kind: str,
) -> dict[str, Any]:
    """Compare a completed or bounded waveform query after same-time updates."""
    names = [signal["name"] for signal in query["selected_signals"]]
    expected_names = [name for name in names if _matches_signal(name, expected)]
    actual_names = [name for name in names if _matches_signal(name, actual)]
    if len(expected_names) != 1 or len(actual_names) != 1:
        raise RtlAssError(
            "wave_diff_ambiguous",
            "expected and actual patterns must each match exactly one signal",
            {"expected_matches": expected_names, "actual_matches": actual_names},
        )
    expected_name = expected_names[0]
    actual_name = actual_names[0]
    if expected_name == actual_name:
        raise RtlAssError(
            "wave_diff_same_signal",
            "expected and actual patterns resolved to the same signal",
            {"signal": expected_name},
        )
    current: dict[str, str] = {}
    first: dict[str, Any] | None = None
    events = query["events"]
    index = 0
    while index < len(events):
        timestamp = events[index]["time"]
        while index < len(events) and events[index]["time"] == timestamp:
            current[events[index]["signal"]] = events[index]["value"]
            index += 1
        if expected_name in current and actual_name in current and current[expected_name] != current[actual_name]:
            first = {
                "time": timestamp,
                "expected_signal": expected_name,
                "expected_value": current[expected_name],
                "actual_signal": actual_name,
                "actual_value": current[actual_name],
            }
            break
    return {
        "schema_version": "1.0",
        "kind": kind,
        "status": "found"
        if first
        else "not_found"
        if query["status"] == "complete"
        else "not_found_in_truncated_window",
        "waveform": query["waveform"],
        "waveform_hash": query["waveform_hash"],
        "timescale": query["timescale"],
        "window": query["window"],
        "first_divergence": first,
        **({"conversion": query["conversion"]} if "conversion" in query else {}),
    }


def _parse_value_change(line: str, line_number: int) -> tuple[str, str]:
    if line[0] in "01xXzZ":
        if len(line) < 2:
            raise RtlAssError("invalid_vcd", "scalar value change lacks an identifier", {"line": line_number})
        return line[0].lower(), line[1:].strip()
    if line[0] in "bBrR":
        fields = line.split()
        if len(fields) != 2 or len(fields[0]) < 2:
            raise RtlAssError("invalid_vcd", "vector or real value change is malformed", {"line": line_number})
        return fields[0][1:].lower(), fields[1]
    raise RtlAssError("invalid_vcd", "unsupported VCD value change", {"line": line_number, "value": line})
