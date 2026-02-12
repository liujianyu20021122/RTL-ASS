#!/usr/bin/env python3
"""Build deterministic skill, SPDX SBOM, and checksum assets for RTL-ASS 1.1."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.1.0"
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


def _build_skill_archive(destination: Path) -> None:
    skill_root = ROOT / ".agents" / "skills" / "rtl-ass"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in SKILL_FILES:
            source = skill_root / relative
            if not source.is_file():
                raise RuntimeError(f"required skill file is missing: {relative}")
            info = zipfile.ZipInfo(f"rtl-ass/{relative}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if relative == "scripts/rtl_ass.py" else 0o644) << 16
            archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


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


def build_assets(dist: Path) -> list[Path]:
    dist.mkdir(parents=True, exist_ok=True)
    wheel = dist / f"rtl_ass-{VERSION}-py3-none-any.whl"
    source = dist / f"rtl_ass-{VERSION}.tar.gz"
    missing = [path.name for path in (wheel, source) if not path.is_file()]
    if missing:
        raise RuntimeError(f"build wheel and sdist before release assets: {', '.join(missing)}")

    skill = dist / f"rtl-ass-skill-{VERSION}.zip"
    _build_skill_archive(skill)
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
            "creators": ["Tool: RTL-ASS-build_release_assets-1.1.0"],
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
