#!/usr/bin/env python3
"""Build deterministic skill, SPDX SBOM, and checksum assets for RTL-ASS 1.2."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import stat
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.2.0"
SKILL_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
    "references/knowledge-governance.md",
    "references/rtl-design.md",
    "references/synthesis-sta.md",
    "references/task-routing.md",
    "references/verification.md",
    "references/waveform-debugging.md",
    "scripts/rtl_ass.py",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_text(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _zip_member(archive: zipfile.ZipFile, name: str, content: bytes, *, executable: bool = False) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (0o755 if executable else 0o644) << 16
    archive.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _build_skill_archive(destination: Path, wheel: Path) -> None:
    skill_root = ROOT / ".agents" / "skills" / "rtl-ass"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in SKILL_FILES:
            source = skill_root / relative
            if not source.is_file():
                raise RuntimeError(f"required skill file is missing: {relative}")
            _zip_member(
                archive,
                f"rtl-ass/{relative}",
                source.read_bytes(),
                executable=relative == "scripts/rtl_ass.py",
            )
        _zip_member(archive, f"rtl-ass/runtime/{wheel.name}", wheel.read_bytes())
        checksum = f"{_sha256(wheel)}  {wheel.name}\n".encode("ascii")
        _zip_member(archive, "rtl-ass/runtime/SHA256SUMS", checksum)


def _spdx_package(path: Path, identifier: str, kind: str) -> dict[str, Any]:
    return {
        "SPDXID": identifier,
        "name": path.name,
        "versionInfo": VERSION,
        "downloadLocation": f"https://github.com/liujianyu20021122/RTL-ASS/releases/download/v{VERSION}/{path.name}",
        "filesAnalyzed": False,
        "licenseConcluded": "Apache-2.0",
        "licenseDeclared": "Apache-2.0",
        "copyrightText": "NOASSERTION",
        "checksums": [{"algorithm": "SHA256", "checksumValue": _sha256(path)}],
        "externalRefs": [
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": f"pkg:generic/rtl-ass-{kind}@{VERSION}",
            }
        ],
    }


def _metadata_version(content: bytes, source: str) -> str:
    metadata = BytesParser().parsebytes(content)
    if metadata.get("Name") != "rtl-ass" or metadata.get("Version") != VERSION:
        raise RuntimeError(f"{source} contains unexpected project metadata")
    return metadata["Version"]


def _validate_wheel(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            bad_member = archive.testzip()
            members = archive.infolist()
            member_names = [member.filename for member in members]
            names = set(member_names)
            metadata_name = f"rtl_ass-{VERSION}.dist-info/METADATA"
            wheel_name = f"rtl_ass-{VERSION}.dist-info/WHEEL"
            if len(names) != len(member_names):
                raise RuntimeError("wheel contains duplicate members")
            if any(_unsafe_archive_name(name) for name in member_names):
                raise RuntimeError("wheel contains an unsafe member path")
            if any(_invalid_zip_member(member) for member in members):
                raise RuntimeError("wheel contains a link, special, or encrypted member")
            if bad_member is not None or metadata_name not in names or wheel_name not in names:
                raise RuntimeError("wheel is corrupt or missing required distribution metadata")
            _metadata_version(archive.read(metadata_name), path.name)
            wheel_metadata = archive.read(wheel_name).decode("utf-8")
            if "Root-Is-Purelib: true" not in wheel_metadata or "Tag: py3-none-any" not in wheel_metadata:
                raise RuntimeError("wheel does not declare the expected portable pure-Python tag")
            if "rtl_ass/__init__.py" not in names or "rtl_ass/cli.py" not in names:
                raise RuntimeError("wheel is missing the runtime package")
    except (OSError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        raise RuntimeError(f"invalid wheel: {path.name}") from exc


def _validate_sdist(path: Path) -> None:
    prefix = f"rtl_ass-{VERSION}/"
    try:
        with tarfile.open(path, mode="r:gz") as archive:
            members = archive.getmembers()
            member_names = [member.name for member in members]
            names = set(member_names)
            required = {f"{prefix}PKG-INFO", f"{prefix}pyproject.toml", f"{prefix}src/rtl_ass/__init__.py"}
            if len(names) != len(member_names):
                raise RuntimeError("sdist contains duplicate members")
            if not required.issubset(names):
                raise RuntimeError("sdist is missing required source or metadata files")
            if any(_unsafe_archive_name(member.name) or not (member.isfile() or member.isdir()) for member in members):
                raise RuntimeError("sdist contains a link, special, or unsafe member")
            for member in members:
                if not member.isfile():
                    continue
                payload_file = archive.extractfile(member)
                if payload_file is None:
                    raise RuntimeError("sdist contains an unreadable regular member")
                _validate_portable_text(payload_file.read(), member.name)
            metadata_file = archive.extractfile(f"{prefix}PKG-INFO")
            if metadata_file is None:
                raise RuntimeError("sdist PKG-INFO is not a regular file")
            _metadata_version(metadata_file.read(), path.name)
    except (OSError, tarfile.TarError) as exc:
        raise RuntimeError(f"invalid sdist: {path.name}") from exc


def _validate_portable_text(content: bytes, source: str) -> None:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return
    unix_home = re.search(r"/(?:home|Users)/[A-Za-z0-9._-]+", text)
    windows_home = re.search(r"(?i)[A-Z]:\\Users\\[^\\\s\"']+", text)
    if unix_home is not None or windows_home is not None:
        raise RuntimeError(f"sdist contains a workstation-specific absolute path: {source}")


def _unsafe_archive_name(name: str) -> bool:
    path = PurePosixPath(name)
    return not name or path.is_absolute() or ".." in path.parts or "\\" in name


def _invalid_zip_member(member: zipfile.ZipInfo) -> bool:
    mode = member.external_attr >> 16
    invalid_mode = bool(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))
    return bool(member.flag_bits & 0x1) or invalid_mode


def _normalize_sdist(path: Path) -> None:
    try:
        epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
    except ValueError as exc:
        raise RuntimeError("SOURCE_DATE_EPOCH must be a nonnegative integer") from exc
    if epoch < 0:
        raise RuntimeError("SOURCE_DATE_EPOCH must be a nonnegative integer")
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with tarfile.open(path, mode="r:gz") as source, temporary.open("wb") as raw_output:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw_output, mtime=epoch) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as destination:
                    for member in sorted(source.getmembers(), key=lambda item: item.name):
                        member.uid = 0
                        member.gid = 0
                        member.uname = ""
                        member.gname = ""
                        member.mtime = epoch
                        member.pax_headers = {}
                        payload = source.extractfile(member) if member.isfile() else None
                        destination.addfile(member, payload)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_assets(dist: Path) -> list[Path]:
    dist.mkdir(parents=True, exist_ok=True)
    wheel = dist / f"rtl_ass-{VERSION}-py3-none-any.whl"
    source = dist / f"rtl_ass-{VERSION}.tar.gz"
    missing = [path.name for path in (wheel, source) if not path.is_file()]
    if missing:
        raise RuntimeError(f"build wheel and sdist before release assets: {', '.join(missing)}")
    _validate_wheel(wheel)
    _validate_sdist(source)
    _normalize_sdist(source)
    _validate_sdist(source)

    skill = dist / f"rtl-ass-skill-{VERSION}.zip"
    _build_skill_archive(skill, wheel)
    packages = [
        _spdx_package(wheel, "SPDXRef-Package-Wheel", "wheel"),
        _spdx_package(source, "SPDXRef-Package-Sdist", "sdist"),
        _spdx_package(skill, "SPDXRef-Package-Skill", "skill"),
    ]
    sbom = dist / "rtl-ass-sbom.spdx.json"
    document = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"RTL-ASS-{VERSION}-release",
        "documentNamespace": f"https://github.com/liujianyu20021122/RTL-ASS/releases/tag/v{VERSION}/sbom",
        "creationInfo": {
            "created": "2026-09-01T00:00:00Z",
            "creators": ["Tool: RTL-ASS-build_release_assets-1.2.0"],
            "licenseListVersion": "3.27",
        },
        "packages": packages,
        "relationships": [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": package["SPDXID"],
            }
            for package in packages
        ],
    }
    _atomic_text(sbom, json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n")

    assets = [wheel, source, skill, sbom]
    checksums = dist / "SHA256SUMS"
    _atomic_text(checksums, "".join(f"{_sha256(path)}  {path.name}\n" for path in assets))
    return [*assets, checksums]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    arguments = parser.parse_args()
    assets = build_assets(arguments.dist.resolve())
    print(json.dumps({"version": VERSION, "assets": [path.name for path in assets]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
