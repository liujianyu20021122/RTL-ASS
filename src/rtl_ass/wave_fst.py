"""Resource-bounded FST conversion and waveform queries."""

from __future__ import annotations

import os
import selectors
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

from rtl_ass.errors import RtlAssError
from rtl_ass.evidence_common import validate_timeout
from rtl_ass.integrity import hash_file
from rtl_ass.wave import build_first_divergence, query_vcd

DEFAULT_MAX_CONVERTED_BYTES = 256 * 1024 * 1024
MAX_CONVERTED_BYTES = 2 * 1024 * 1024 * 1024


def query_fst(
    path: str | Path,
    *,
    patterns: Iterable[str],
    start_time: int = 0,
    end_time: int | None = None,
    max_events: int = 1000,
    conversion_timeout_seconds: int = 60,
    max_converted_bytes: int = DEFAULT_MAX_CONVERTED_BYTES,
) -> dict[str, Any]:
    source = _validate_fst(path)
    validate_timeout(conversion_timeout_seconds)
    _validate_conversion_limit(max_converted_bytes)
    executable = shutil.which("fst2vcd")
    if executable is None:
        raise RtlAssError(
            "wave_tool_unavailable",
            "FST queries require the open-source fst2vcd converter",
            {"tool": "fst2vcd"},
        )
    initial_hash = hash_file(source)
    with tempfile.TemporaryDirectory(prefix="rtl-ass-fst-") as directory:
        converted = Path(directory) / "converted.vcd"
        command = [executable, "-f", str(source.resolve())]
        _run_bounded_conversion(
            command,
            converted=converted,
            timeout_seconds=conversion_timeout_seconds,
            max_bytes=max_converted_bytes,
        )
        query = query_vcd(
            converted,
            patterns=patterns,
            start_time=start_time,
            end_time=end_time,
            max_events=max_events,
        )
        converted_hash = query["waveform_hash"]
        final_hash = hash_file(source)
        if final_hash != initial_hash:
            raise RtlAssError(
                "waveform_changed",
                "FST changed while it was being converted or queried",
                {"path": str(source), "initial_hash": initial_hash, "final_hash": final_hash},
            )
    query.update(
        {
            "kind": "fst-query",
            "waveform": source.as_posix(),
            "waveform_hash": initial_hash,
            "conversion": {
                "tool": {"name": "fst2vcd", "binary_hash": hash_file(executable)},
                "command": command,
                "converted_vcd_hash": converted_hash,
                "timeout_seconds": conversion_timeout_seconds,
                "max_converted_bytes": max_converted_bytes,
            },
        }
    )
    return query


def first_divergence_fst(
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
    query = query_fst(
        path,
        patterns=(expected, actual),
        start_time=start_time,
        end_time=end_time,
        max_events=max_events,
        conversion_timeout_seconds=conversion_timeout_seconds,
        max_converted_bytes=max_converted_bytes,
    )
    return build_first_divergence(
        query,
        expected=expected,
        actual=actual,
        kind="fst-first-divergence",
    )


def _validate_fst(path: str | Path) -> Path:
    source = Path(path)
    if not source.is_file() or source.suffix.lower() != ".fst":
        raise RtlAssError("waveform_not_found", "FST input must be an existing .fst file", {"path": str(source)})
    return source


def _validate_conversion_limit(max_bytes: int) -> None:
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= MAX_CONVERTED_BYTES:
        raise RtlAssError(
            "invalid_wave_conversion_limit",
            f"max converted bytes must be an integer between 1 and {MAX_CONVERTED_BYTES}",
            {"max_converted_bytes": max_bytes},
        )


def _run_bounded_conversion(
    command: list[str],
    *,
    converted: Path,
    timeout_seconds: int,
    max_bytes: int,
) -> None:
    started = time.monotonic()
    stderr_tail = bytearray()
    converted_bytes = 0
    with converted.open("wb") as converted_stream:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if process.stdout is None or process.stderr is None:
            _stop_process(process)
            raise RtlAssError("wave_conversion_failed", "failed to capture fst2vcd output streams")
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ, "stdout")
                selector.register(process.stderr, selectors.EVENT_READ, "stderr")
                while selector.get_map():
                    remaining = timeout_seconds - (time.monotonic() - started)
                    if remaining <= 0:
                        _stop_process(process)
                        raise RtlAssError(
                            "wave_conversion_timeout",
                            "FST conversion exceeded the configured timeout",
                            {"timeout_seconds": timeout_seconds},
                        )
                    for key, _mask in selector.select(timeout=min(remaining, 0.1)):
                        chunk = os.read(key.fd, 64 * 1024)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        if key.data == "stdout":
                            converted_bytes += len(chunk)
                            if converted_bytes > max_bytes:
                                _stop_process(process)
                                raise RtlAssError(
                                    "wave_conversion_too_large",
                                    "converted VCD exceeded the configured byte limit",
                                    {"max_converted_bytes": max_bytes},
                                )
                            converted_stream.write(chunk)
                        else:
                            stderr_tail.extend(chunk)
                            if len(stderr_tail) > 1000:
                                del stderr_tail[:-1000]
            try:
                returncode = process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                _stop_process(process)
                raise RtlAssError(
                    "wave_conversion_timeout",
                    "fst2vcd did not terminate after closing its output streams",
                    {"timeout_seconds": timeout_seconds},
                ) from None
        finally:
            process.stdout.close()
            process.stderr.close()
    if returncode != 0:
        raise RtlAssError(
            "wave_conversion_failed",
            "fst2vcd failed to convert the waveform",
            {"returncode": returncode, "stderr_tail": stderr_tail.decode(errors="replace")},
        )
    if not converted.is_file():
        raise RtlAssError("wave_conversion_failed", "fst2vcd did not produce a VCD output")


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)
