#!/usr/bin/env python3
"""Run RTL-ASS from a source checkout without installing the package."""

from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
SCRIPT_DIRECTORY = Path(__file__).resolve().parent

sys.path = [entry for entry in sys.path if Path(entry).resolve() != SCRIPT_DIRECTORY]

if SOURCE_ROOT.is_dir():
    sys.path.insert(0, str(SOURCE_ROOT))

try:
    from rtl_ass.cli import main
except ModuleNotFoundError as exc:
    raise SystemExit(
        "RTL-ASS helper package is unavailable; install the rtl-ass wheel or run this skill from its repository"
    ) from exc

if __name__ == "__main__":
    raise SystemExit(main())
