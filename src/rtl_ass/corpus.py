"""Reproducible, quarantine-only audit of downloaded GitHub corpus sources."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable

from rtl_ass.errors import RtlAssError
from rtl_ass.integrity import hash_bytes, hash_json, utc_now

_TB_PATH = re.compile(r"(?:^|[/_.-])(tb|testbench|tests?|sim|verification|verify)(?:[/_.-]|$)", re.IGNORECASE)
_ASSERTION_PATH = re.compile(r"(?:^|[/_.-])(formal|assertions?|properties|sva)(?:[/_.-]|$)", re.IGNORECASE)
_BENCHMARK_PATH = re.compile(
    r"(?:^|[/_.-])(benchmarks?|datasets?|evals?|golden|reference-solutions?|hdlbits|verilog-eval)(?:[/_.-]|$)",
    re.IGNORECASE,
)
_LICENSE_NAMES = ("LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING", "COPYING.txt")

_LICENSE_SIGNATURES = (
    ("Apache-2.0", "apache license", "version 2.0"),
    ("MIT", "mit license", "permission is hereby granted"),
    ("MIT", "permission is hereby granted", 'the software is provided "as is"'),
    ("GPL-2.0-family", "gnu general public license", "version 2"),
    ("GPL-3.0-family", "gnu general public license", "version 3"),
    ("BSD-3-Clause", "redistribution and use in source and binary forms", "neither the name"),
    ("ISC", "permission to use, copy, modify, and/or distribute", 'the software is provided "as is"'),
    ("Solderpad-2.1", "solderpad hardware license", "version 2.1"),
)


def _git(path: Path, arguments: list[str]) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), *arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RtlAssError(
            "git_audit_failed",
            "failed to read pinned corpus repository metadata",
            {"repository": path.name, "arguments": arguments, "stderr": result.stderr.strip()},
        )
    return result.stdout.strip()


def _tracked_files(path: Path) -> tuple[str, ...]:
    if (path / ".git").is_dir():
        output = subprocess.run(
            ["git", "-C", str(path), "ls-files", "-z"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
        if output.returncode != 0:
            raise RtlAssError(
                "git_audit_failed",
                "failed to enumerate corpus repository files",
                {"repository": path.name, "stderr": output.stderr.decode(errors="replace").strip()},
            )
        return tuple(item.decode("utf-8", errors="surrogateescape") for item in output.stdout.split(b"\0") if item)
    return tuple(
        candidate.relative_to(path).as_posix()
        for candidate in sorted(path.rglob("*"))
        if candidate.is_file() and ".git" not in candidate.parts
    )


def _find_license(path: Path) -> dict[str, Any]:
    license_path = next((path / name for name in _LICENSE_NAMES if (path / name).is_file()), None)
    if license_path is None:
        return {
            "status": "unknown",
            "spdx_candidate": None,
            "path": None,
            "content_hash": None,
            "requires_review": True,
        }
    content = license_path.read_bytes()
    normalized = content.decode("utf-8", errors="replace").lower()
    candidate = next(
        (spdx for spdx, first, second in _LICENSE_SIGNATURES if first in normalized and second in normalized),
        None,
    )
    return {
        "status": "detected" if candidate else "unknown",
        "spdx_candidate": candidate,
        "path": license_path.name,
        "content_hash": hash_bytes(content),
        "requires_review": True,
    }


def _count_roles(files: Iterable[str]) -> dict[str, int]:
    counts = {
        "tracked_files": 0,
        "verilog_files": 0,
        "systemverilog_files": 0,
        "rtl_source_candidates": 0,
        "testbench_candidates": 0,
        "assertion_candidates": 0,
        "benchmark_contamination_candidates": 0,
    }
    for filename in files:
        counts["tracked_files"] += 1
        suffix = Path(filename).suffix.lower()
        if suffix in {".v", ".vh"}:
            counts["verilog_files"] += 1
        elif suffix in {".sv", ".svh"}:
            counts["systemverilog_files"] += 1
        else:
            continue
        counts["rtl_source_candidates"] += 1
        if _TB_PATH.search(filename):
            counts["testbench_candidates"] += 1
        if _ASSERTION_PATH.search(filename):
            counts["assertion_candidates"] += 1
        if _BENCHMARK_PATH.search(filename):
            counts["benchmark_contamination_candidates"] += 1
    return counts


def audit_source(path: Path) -> dict[str, Any]:
    is_git = (path / ".git").is_dir()
    files = _tracked_files(path)
    if is_git:
        revision = _git(path, ["rev-parse", "HEAD"])
        revision_date = _git(path, ["log", "-1", "--format=%cI"])
        source_uri = _git(path, ["remote", "get-url", "origin"])
        source_kind = "git"
    else:
        revision = None
        revision_date = None
        source_uri = None
        source_kind = "archive-or-directory"
    license_finding = _find_license(path)
    counts = _count_roles(files)
    contamination_count = counts["benchmark_contamination_candidates"]
    identity_input = {
        "name": path.name,
        "source_uri": source_uri,
        "revision": revision,
        "license_hash": license_finding["content_hash"],
        "counts": counts,
    }
    return {
        "name": path.name,
        "source_kind": source_kind,
        "source_uri": source_uri,
        "revision": revision,
        "revision_date": revision_date,
        "reproducibly_pinned": revision is not None,
        "license_finding": license_finding,
        "counts": counts,
        "intended_roles": [
            role
            for role, count_key in (
                ("rtl-design", "rtl_source_candidates"),
                ("testbench", "testbench_candidates"),
                ("assertion", "assertion_candidates"),
            )
            if counts[count_key] > 0
        ],
        "trust_status": "quarantine",
        "trusted_retrieval_eligible": False,
        "benchmark_contamination_risk": "high"
        if contamination_count >= 100
        else "medium"
        if contamination_count
        else "not_detected",
        "ingestion_status": "not_ingested",
        "source_identity": hash_json(identity_input),
    }


def audit_corpus(root: str | Path) -> dict[str, Any]:
    source_root = Path(root)
    if not source_root.is_dir():
        raise RtlAssError("corpus_not_found", "corpus source root does not exist", {"path": str(source_root)})
    sources = [audit_source(path) for path in sorted(source_root.iterdir()) if path.is_dir()]
    return {
        "schema_version": "1.0",
        "generated_at": utc_now(),
        "source_root": source_root.as_posix(),
        "source_count": len(sources),
        "sources": sources,
        "policy": {
            "default_trust": "quarantine",
            "license_findings_are_automated_heuristics": True,
            "source_execution_performed": False,
            "redistribution_approved": False,
        },
    }


def write_manifest_atomic(manifest: dict[str, Any], output_path: str | Path) -> Path:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, destination)
    return destination
