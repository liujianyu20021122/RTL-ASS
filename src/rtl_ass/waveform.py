"""Stable format-dispatch facade for bounded waveform queries."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from rtl_ass.errors import RtlAssError
from rtl_ass.integrity import canonical_json, hash_file
from rtl_ass.wave import first_divergence_vcd, query_vcd
from rtl_ass.wave_fst import DEFAULT_MAX_CONVERTED_BYTES, first_divergence_fst, query_fst

_WAVE_KINDS = frozenset({"vcd-query", "fst-query", "vcd-first-divergence", "fst-first-divergence"})
_WAVE_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "status",
        "waveform",
        "waveform_hash",
        "timescale",
        "window",
        "patterns",
        "selected_signals",
        "event_count",
        "events",
        "first_divergence",
        "conversion",
    }
)


def query_waveform(
    path: str | Path,
    *,
    patterns: Iterable[str],
    start_time: int = 0,
    end_time: int | None = None,
    max_events: int = 1000,
    conversion_timeout_seconds: int = 60,
    max_converted_bytes: int = DEFAULT_MAX_CONVERTED_BYTES,
) -> dict[str, Any]:
    suffix = Path(path).suffix.lower()
    if suffix == ".vcd":
        return query_vcd(path, patterns=patterns, start_time=start_time, end_time=end_time, max_events=max_events)
    if suffix == ".fst":
        return query_fst(
            path,
            patterns=patterns,
            start_time=start_time,
            end_time=end_time,
            max_events=max_events,
            conversion_timeout_seconds=conversion_timeout_seconds,
            max_converted_bytes=max_converted_bytes,
        )
    raise RtlAssError(
        "unsupported_waveform",
        "waveform queries support only .vcd and .fst files",
        {"path": str(path)},
    )


def first_divergence_waveform(
    path: str | Path,
    *,
    expected: str,
    actual: str,
    start_time: int = 0,
    end_time: int | None = None,
    max_events: int = 100_000,
    conversion_timeout_seconds: int = 60,
    max_converted_bytes: int = DEFAULT_MAX_CONVERTED_BYTES,
) -> dict[str, Any]:
    suffix = Path(path).suffix.lower()
    if suffix == ".vcd":
        return first_divergence_vcd(
            path,
            expected=expected,
            actual=actual,
            start_time=start_time,
            end_time=end_time,
            max_events=max_events,
        )
    if suffix == ".fst":
        return first_divergence_fst(
            path,
            expected=expected,
            actual=actual,
            start_time=start_time,
            end_time=end_time,
            max_events=max_events,
            conversion_timeout_seconds=conversion_timeout_seconds,
            max_converted_bytes=max_converted_bytes,
        )
    raise RtlAssError(
        "unsupported_waveform",
        "waveform queries support only .vcd and .fst files",
        {"path": str(path)},
    )


def validate_waveform_evidence(
    value: Mapping[str, Any],
    *,
    require_current_waveform: bool = False,
) -> dict[str, Any]:
    """Validate the stable waveform result contract without interpreting its claim."""

    try:
        canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise RtlAssError("invalid_waveform_evidence", "waveform evidence must contain finite JSON values") from exc
    unknown = sorted(set(value).difference(_WAVE_FIELDS))
    kind = value.get("kind")
    status = value.get("status")
    waveform = value.get("waveform")
    waveform_hash = value.get("waveform_hash")
    timescale = value.get("timescale")
    window = value.get("window")
    if (
        unknown
        or value.get("schema_version") != "1.0"
        or kind not in _WAVE_KINDS
        or not isinstance(waveform, str)
        or not waveform
        or not isinstance(waveform_hash, str)
        or len(waveform_hash) != 64
        or any(character not in "0123456789abcdef" for character in waveform_hash)
        or not isinstance(timescale, str)
        or not timescale
        or not isinstance(window, dict)
        or set(window) != {"start", "end"}
        or isinstance(window.get("start"), bool)
        or not isinstance(window.get("start"), int)
        or window["start"] < 0
        or not (window.get("end") is None or isinstance(window.get("end"), int))
        or isinstance(window.get("end"), bool)
        or (isinstance(window.get("end"), int) and window["end"] < window["start"])
    ):
        raise RtlAssError("invalid_waveform_evidence", "waveform evidence does not match the stable contract")
    if kind in {"vcd-query", "fst-query"}:
        if status not in {"complete", "truncated"} or "first_divergence" in value:
            raise RtlAssError("invalid_waveform_evidence", "waveform query evidence is incomplete or inconsistent")
        _validate_query_payload(value, window)
    else:
        if (
            status not in {"found", "not_found", "not_found_in_truncated_window"}
            or "first_divergence" not in value
            or any(field in value for field in ("patterns", "selected_signals", "event_count", "events"))
        ):
            raise RtlAssError("invalid_waveform_evidence", "waveform divergence evidence is incomplete or inconsistent")
        _validate_divergence_payload(value["first_divergence"], status=status, window=window)
    is_fst = kind.startswith("fst-")
    if is_fst != ("conversion" in value):
        raise RtlAssError("invalid_waveform_evidence", "FST evidence requires one conversion identity")
    if is_fst:
        _validate_conversion(value["conversion"])
    if require_current_waveform:
        source = Path(waveform)
        if not source.is_file() or source.is_symlink() or hash_file(source) != waveform_hash:
            raise RtlAssError("waveform_evidence_changed", "waveform input no longer matches its evidence hash")
    return dict(value)


def _validate_query_payload(value: Mapping[str, Any], window: Mapping[str, Any]) -> None:
    patterns = value.get("patterns")
    signals = value.get("selected_signals")
    events = value.get("events")
    event_count = value.get("event_count")
    if (
        not isinstance(patterns, list)
        or not patterns
        or not all(isinstance(pattern, str) and pattern for pattern in patterns)
        or not isinstance(signals, list)
        or not isinstance(events, list)
        or isinstance(event_count, bool)
        or not isinstance(event_count, int)
        or event_count != len(events)
    ):
        raise RtlAssError("invalid_waveform_evidence", "waveform query evidence is incomplete or inconsistent")
    signal_names: set[str] = set()
    for signal in signals:
        if (
            not isinstance(signal, dict)
            or set(signal) != {"name", "identifier", "width", "variable_type"}
            or not all(
                isinstance(signal[field], str) and signal[field] for field in ("name", "identifier", "variable_type")
            )
            or isinstance(signal["width"], bool)
            or not isinstance(signal["width"], int)
            or signal["width"] < 1
            or signal["name"] in signal_names
        ):
            raise RtlAssError("invalid_waveform_evidence", "waveform selected-signal metadata is invalid")
        signal_names.add(signal["name"])
    for event in events:
        if (
            not isinstance(event, dict)
            or set(event) != {"time", "signal", "value"}
            or isinstance(event["time"], bool)
            or not isinstance(event["time"], int)
            or not _time_in_window(event["time"], window)
            or event["signal"] not in signal_names
            or not isinstance(event["value"], str)
            or not event["value"]
        ):
            raise RtlAssError("invalid_waveform_evidence", "waveform event metadata is invalid")


def _validate_divergence_payload(value: object, *, status: object, window: Mapping[str, Any]) -> None:
    if status != "found":
        if value is not None:
            raise RtlAssError("invalid_waveform_evidence", "a non-found waveform result requires null divergence")
        return
    fields = {"time", "expected_signal", "expected_value", "actual_signal", "actual_value"}
    if (
        not isinstance(value, dict)
        or set(value) != fields
        or isinstance(value["time"], bool)
        or not isinstance(value["time"], int)
        or not _time_in_window(value["time"], window)
        or not all(
            isinstance(value[field], str) and value[field]
            for field in ("expected_signal", "expected_value", "actual_signal", "actual_value")
        )
        or value["expected_signal"] == value["actual_signal"]
    ):
        raise RtlAssError("invalid_waveform_evidence", "waveform first-divergence metadata is invalid")


def _time_in_window(timestamp: int, window: Mapping[str, Any]) -> bool:
    end = window["end"]
    return timestamp >= window["start"] and (end is None or timestamp <= end)


def _validate_conversion(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {
        "tool",
        "command",
        "converted_vcd_hash",
        "timeout_seconds",
        "max_converted_bytes",
    }:
        raise RtlAssError("invalid_waveform_evidence", "FST conversion identity is invalid")
    tool = value["tool"]
    command = value["command"]
    converted_hash = value["converted_vcd_hash"]
    timeout = value["timeout_seconds"]
    byte_limit = value["max_converted_bytes"]
    if (
        not isinstance(tool, dict)
        or set(tool) != {"name", "binary_hash"}
        or tool.get("name") != "fst2vcd"
        or not isinstance(tool.get("binary_hash"), str)
        or len(tool["binary_hash"]) != 64
        or any(character not in "0123456789abcdef" for character in tool["binary_hash"])
        or not isinstance(command, list)
        or not command
        or not all(isinstance(argument, str) and argument for argument in command)
        or not isinstance(converted_hash, str)
        or len(converted_hash) != 64
        or any(character not in "0123456789abcdef" for character in converted_hash)
        or isinstance(timeout, bool)
        or not isinstance(timeout, int)
        or not 1 <= timeout <= 3600
        or isinstance(byte_limit, bool)
        or not isinstance(byte_limit, int)
        or not 1 <= byte_limit <= 2 * 1024 * 1024 * 1024
    ):
        raise RtlAssError("invalid_waveform_evidence", "FST conversion identity is invalid")
