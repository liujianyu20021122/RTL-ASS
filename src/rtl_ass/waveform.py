"""Stable format-dispatch facade for bounded waveform queries."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from rtl_ass.errors import RtlAssError
from rtl_ass.wave import first_divergence_vcd, query_vcd
from rtl_ass.wave_fst import DEFAULT_MAX_CONVERTED_BYTES, first_divergence_fst, query_fst


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
