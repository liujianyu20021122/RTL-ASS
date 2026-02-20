from __future__ import annotations

import io
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.build_release_assets import VERSION, _validate_sdist, _validate_wheel, build_assets


class ReleaseAssetTests(unittest.TestCase):
    def test_fake_distributions_are_rejected_before_auxiliary_assets_are_created(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dist = Path(directory)
            (dist / f"rtl_ass-{VERSION}-py3-none-any.whl").write_bytes(b"not a wheel")
            (dist / f"rtl_ass-{VERSION}.tar.gz").write_bytes(b"not an sdist")

            with self.assertRaisesRegex(RuntimeError, "invalid wheel"):
                build_assets(dist)

            self.assertFalse((dist / f"rtl-ass-skill-{VERSION}.zip").exists())
            self.assertFalse((dist / "rtl-ass-sbom.spdx.json").exists())
            self.assertFalse((dist / "SHA256SUMS").exists())

    def test_parseable_distributions_with_unsafe_or_duplicate_members_are_rejected(self) -> None:
        metadata = f"Name: rtl-ass\nVersion: {VERSION}\n\n".encode()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel = root / f"rtl_ass-{VERSION}-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr(f"rtl_ass-{VERSION}.dist-info/METADATA", metadata)
                archive.writestr(
                    f"rtl_ass-{VERSION}.dist-info/WHEEL",
                    "Root-Is-Purelib: true\nTag: py3-none-any\n",
                )
                archive.writestr("rtl_ass/__init__.py", "")
                archive.writestr("rtl_ass/cli.py", "")
                archive.writestr("../escape", "")
            with self.assertRaisesRegex(RuntimeError, "unsafe member"):
                _validate_wheel(wheel)

            sdist = root / f"rtl_ass-{VERSION}.tar.gz"
            prefix = f"rtl_ass-{VERSION}/"
            with tarfile.open(sdist, "w:gz") as archive:
                for name, content in (
                    (f"{prefix}PKG-INFO", metadata),
                    (f"{prefix}pyproject.toml", b""),
                    (f"{prefix}src/rtl_ass/__init__.py", b""),
                    (f"{prefix}pyproject.toml", b"duplicate"),
                ):
                    member = tarfile.TarInfo(name)
                    member.size = len(content)
                    archive.addfile(member, io.BytesIO(content))
            with self.assertRaisesRegex(RuntimeError, "duplicate members"):
                _validate_sdist(sdist)

    def test_sdist_rejects_workstation_specific_absolute_paths(self) -> None:
        metadata = f"Name: rtl-ass\nVersion: {VERSION}\n\n".encode()
        leaked_path = ("/" + "home/developer/private.v").encode()
        with tempfile.TemporaryDirectory() as directory:
            sdist = Path(directory) / f"rtl_ass-{VERSION}.tar.gz"
            prefix = f"rtl_ass-{VERSION}/"
            with tarfile.open(sdist, "w:gz") as archive:
                for name, content in (
                    (f"{prefix}PKG-INFO", metadata),
                    (f"{prefix}pyproject.toml", b""),
                    (f"{prefix}src/rtl_ass/__init__.py", leaked_path),
                ):
                    member = tarfile.TarInfo(name)
                    member.size = len(content)
                    archive.addfile(member, io.BytesIO(content))

            with self.assertRaisesRegex(RuntimeError, "workstation-specific absolute path"):
                _validate_sdist(sdist)


if __name__ == "__main__":
    unittest.main()
