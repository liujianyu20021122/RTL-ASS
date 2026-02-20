#!/usr/bin/env python3
"""Run RTL-ASS from an audited source checkout, release skill, or installation."""

from __future__ import annotations

import hashlib
import re
import sys
import tomllib
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_DIRECTORY = SCRIPT_PATH.parent
SKILL_ROOT = SCRIPT_DIRECTORY.parent
_WHEEL_NAME = re.compile(r"^rtl_ass-[0-9]+\.[0-9]+\.[0-9]+-py3-none-any\.whl$")
_CHECKSUM = re.compile(r"^([0-9a-f]{64})  ([^/\r\n]+)\n$")

sys.path = [entry for entry in sys.path if Path(entry).resolve() != SCRIPT_DIRECTORY]


def _repository_source() -> Path | None:
    if SKILL_ROOT.parent.name != "skills" or SKILL_ROOT.parent.parent.name != ".agents":
        return None
    repository = SKILL_ROOT.parents[2]
    project_file = repository / "pyproject.toml"
    source = repository / "src"
    package = source / "rtl_ass" / "__init__.py"
    if project_file.is_symlink() or package.is_symlink() or not project_file.is_file() or not package.is_file():
        return None
    try:
        metadata = tomllib.loads(project_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    project = metadata.get("project")
    return source if isinstance(project, dict) and project.get("name") == "rtl-ass" else None


def _bundled_runtime() -> Path | None:
    runtime = SKILL_ROOT / "runtime"
    if runtime.is_symlink():
        raise SystemExit("RTL-ASS bundled runtime directory is invalid")
    if not runtime.exists():
        return None
    if not runtime.is_dir():
        raise SystemExit("RTL-ASS bundled runtime directory is invalid")
    entries = sorted(runtime.iterdir())
    wheels = [path for path in entries if _WHEEL_NAME.fullmatch(path.name)]
    checksum_file = runtime / "SHA256SUMS"
    if (
        len(wheels) != 1
        or set(entries) != {wheels[0], checksum_file}
        or wheels[0].is_symlink()
        or checksum_file.is_symlink()
        or not wheels[0].is_file()
        or not checksum_file.is_file()
    ):
        raise SystemExit("RTL-ASS bundled runtime must contain exactly one wheel and its checksum")
    try:
        checksum_text = checksum_file.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError) as exc:
        raise SystemExit("RTL-ASS bundled runtime checksum is unreadable") from exc
    match = _CHECKSUM.fullmatch(checksum_text)
    if match is None or match.group(2) != wheels[0].name:
        raise SystemExit("RTL-ASS bundled runtime checksum contract is invalid")
    digest = hashlib.sha256()
    with wheels[0].open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != match.group(1):
        raise SystemExit("RTL-ASS bundled runtime wheel failed integrity verification")
    return wheels[0]


source_root = _repository_source()
if source_root is not None:
    sys.path.insert(0, str(source_root))
else:
    bundled_runtime = _bundled_runtime()
    if bundled_runtime is not None:
        sys.path.insert(0, str(bundled_runtime))

try:
    from rtl_ass.cli import main
except ModuleNotFoundError as exc:
    raise SystemExit(
        "RTL-ASS helper package is unavailable; use the release skill, install the wheel, or run from its repository"
    ) from exc

if __name__ == "__main__":
    raise SystemExit(main())
