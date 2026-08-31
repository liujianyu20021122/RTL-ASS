"""Canonical serialization, content identity, and timestamps."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def parse_json(value: str | bytes | bytearray) -> Any:
    return json.loads(value, parse_constant=_reject_nonfinite_json)


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def hash_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_utf8_exact(path: str | Path) -> str:
    """Decode UTF-8 bytes without universal-newline normalization."""
    return Path(path).read_bytes().decode("utf-8")


def hash_json(value: Any) -> str:
    return hash_bytes(canonical_json(value).encode("utf-8"))


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
