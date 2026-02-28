"""Reproducible, repository-scale RTL workflow cases materialized from pinned Git objects."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from rtl_ass.compile_manifest import CompileManifest
from rtl_ass.evidence import run_iverilog_simulation, run_verilator_lint
from rtl_ass.integrity import hash_file

if __package__:
    from .workflow_cases import WorkflowCase, _evidence_view, _git_state, _regular_file
else:
    from workflow_cases import (  # type: ignore[import-not-found,no-redef]
        WorkflowCase,
        _evidence_view,
        _git_state,
        _regular_file,
    )


@dataclass(frozen=True)
class SocSourceSpec:
    identifier: str
    repository_url: str
    base_revision: str
    base_tree: str
    source_file_count: int
    affected_path: str
    affected_source_hash: str
    mutated_source_hash: str
    mutation_before: str
    mutation_after: str
    hidden_revision: str
    hidden_path: str
    hidden_hash: str
    source_license: str
    hidden_license: str


CORE_V_MCU_EVENT_IRQ = SocSourceSpec(
    identifier="soc-core-v-mcu-event-irq",
    repository_url="https://github.com/openhwgroup/core-v-mcu.git",
    base_revision="cf5be30bb048ab51d7f699296c0db702399f243a",
    base_tree="a10e2f3af734726d02f1e3e3df28689576c84a59",
    source_file_count=1414,
    affected_path="rtl/core-v-mcu/soc/soc_event_generator.sv",
    affected_source_hash="df46afdb674b905030e1b0772b55caf36eb544b436bf3ac425d61658c3a4392a",
    mutated_source_hash="6517dd158bd76f15713a66547372e1e447badcb33039edc5b24454b4528c6fe4",
    mutation_before="  assign s_event_fifo_ready = (core_irq_ack_i && (core_irq_ack_id_i == 11));",
    mutation_after="  assign s_event_fifo_ready = core_irq_ack_i;",
    hidden_revision="3a0d194c0030bae3aa3a119fc08b06b2a6d80509",
    hidden_path="rtl/core-v-mcu/soc/soc_event_generator/tb/soc_event_generator_tb.sv",
    hidden_hash="308668985b71bdca21fd7708574339206f97a19f0655767ff84146a3f9af872c",
    source_license="Solderpad Hardware License 0.51 on affected RTL; repository contains per-file licenses",
    hidden_license="Apache-2.0 WITH SHL-2.1",
)

SOC_CASES = {CORE_V_MCU_EVENT_IRQ.identifier: CORE_V_MCU_EVENT_IRQ}


def _git(repository: Path, *arguments: str, binary: bool = False) -> str | bytes:
    result = subprocess.run(
        ["git", "-C", repository.as_posix(), *arguments],
        check=False,
        capture_output=True,
        text=not binary,
        timeout=120,
    )
    if result.returncode != 0:
        stderr = result.stderr if isinstance(result.stderr, str) else result.stderr.decode(errors="replace")
        raise RuntimeError(f"Git source validation failed: {stderr.strip()}")
    output = result.stdout
    if binary:
        if not isinstance(output, bytes):
            raise AssertionError("binary Git invocation returned text")
        return output
    if not isinstance(output, str):
        raise AssertionError("text Git invocation returned bytes")
    return output


def _validated_source(repository: Path, spec: SocSourceSpec) -> dict[str, Any]:
    if not repository.is_dir() or repository.is_symlink():
        raise ValueError("SoC source repository must be a real directory")
    revision = str(_git(repository, "rev-parse", f"{spec.base_revision}^{{commit}}")).strip()
    hidden_revision = str(_git(repository, "rev-parse", f"{spec.hidden_revision}^{{commit}}")).strip()
    tree = str(_git(repository, "show", "-s", "--format=%T", revision)).strip()
    if revision != spec.base_revision or hidden_revision != spec.hidden_revision or tree != spec.base_tree:
        raise ValueError("SoC source revision or tree does not match the audited case specification")
    tree_rows = str(_git(repository, "ls-tree", "-r", revision)).splitlines()
    if len(tree_rows) != spec.source_file_count or any(
        not (row.startswith("100644 blob ") or row.startswith("100755 blob ")) for row in tree_rows
    ):
        raise ValueError("SoC source tree count or file modes do not match the audited case specification")
    affected = _git(repository, "show", f"{revision}:{spec.affected_path}", binary=True)
    hidden = _git(repository, "show", f"{hidden_revision}:{spec.hidden_path}", binary=True)
    if not isinstance(affected, bytes) or not isinstance(hidden, bytes):
        raise AssertionError("binary Git reads must return bytes")
    if hashlib.sha256(affected).hexdigest() != spec.affected_source_hash:
        raise ValueError("affected RTL hash does not match the audited case specification")
    if hashlib.sha256(hidden).hexdigest() != spec.hidden_hash:
        raise ValueError("hidden test hash does not match the audited case specification")
    remotes = str(_git(repository, "remote", "get-url", "--all", "origin")).splitlines()
    return {
        "repository_url": spec.repository_url,
        "observed_origin_urls": remotes,
        "canonical_origin_observed": spec.repository_url in remotes,
        "base_revision": revision,
        "base_tree": tree,
        "source_file_count": len(tree_rows),
        "affected_path": spec.affected_path,
        "affected_source_hash": spec.affected_source_hash,
        "mutated_source_hash": spec.mutated_source_hash,
        "hidden_revision": hidden_revision,
        "hidden_path": spec.hidden_path,
        "hidden_hash": spec.hidden_hash,
        "source_license": spec.source_license,
        "hidden_license": spec.hidden_license,
    }


def _extract_regular_archive(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:") as handle:
        members = handle.getmembers()
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not (member.isdir() or member.isfile()):
                raise ValueError("SoC Git archive contains an unsafe or unsupported member")
        for member in members:
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = handle.extractfile(member)
            if source is None:
                raise ValueError("SoC Git archive contains an unreadable file")
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)


def _materialize_source(spec: SocSourceSpec, source_repository: Path, destination: Path) -> dict[str, Any]:
    if destination.exists():
        raise FileExistsError(f"refusing to reuse materialized SoC case: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    provenance = _validated_source(source_repository.resolve(), spec)
    temporary = Path(tempfile.mkdtemp(prefix=f".{spec.identifier}-", dir=destination.parent))
    try:
        public = temporary / "public"
        private = temporary / "private"
        public.mkdir()
        private.mkdir()
        archive = temporary / "source.tar"
        with archive.open("wb") as output:
            result = subprocess.run(
                ["git", "-C", source_repository.resolve().as_posix(), "archive", "--format=tar", spec.base_revision],
                check=False,
                stdout=output,
                stderr=subprocess.PIPE,
                timeout=120,
            )
        if result.returncode != 0:
            raise RuntimeError(f"Git archive failed: {result.stderr.decode(errors='replace').strip()}")
        _extract_regular_archive(archive, public)
        archive.unlink()

        affected = public / spec.affected_path
        source = affected.read_text(encoding="utf-8")
        if source.count(spec.mutation_before) != 1 or spec.mutation_after in source:
            raise ValueError("SoC defect mutation precondition is not exact")
        affected.write_text(source.replace(spec.mutation_before, spec.mutation_after), encoding="utf-8")
        if hash_file(affected) != spec.mutated_source_hash:
            raise ValueError("materialized SoC defect hash is not reproducible")

        hidden = _git(source_repository.resolve(), "show", f"{spec.hidden_revision}:{spec.hidden_path}", binary=True)
        if not isinstance(hidden, bytes):
            raise AssertionError("binary Git reads must return bytes")
        hidden_path = private / "soc_event_generator_hidden_tb.sv"
        hidden_path.write_bytes(hidden)
        provenance_path = temporary / "source-provenance.json"
        provenance_path.write_text(
            json.dumps({"schema_version": "1.0", "case": spec.identifier, **provenance}, sort_keys=True, indent=2)
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return provenance


def materialize_soc_case(
    identifier: str,
    source_repository: Path,
    destination: Path,
) -> tuple[WorkflowCase, dict[str, Any]]:
    """Create a new, immutable-input SoC fixture and return its executable case contract."""
    try:
        spec = SOC_CASES[identifier]
    except KeyError as exc:
        raise ValueError(f"unknown SoC workflow case: {identifier}") from exc
    provenance = _materialize_source(spec, source_repository, destination)

    case_root = destination
    case = WorkflowCase(
        identifier=identifier,
        prompt="""A CORE-V-MCU regression reports that a pending FC event routed through SoC IRQ 11 is lost when software acknowledges an unrelated interrupt such as IRQ 30 or IRQ 31. Diagnose this in the complete repository and make the smallest RTL repair that preserves the event-generator interface, masking behavior, FIFO CSR semantics, and IRQ 11 acknowledgment sequence. Do not modify existing tests, build metadata, or unrelated RTL. Use only open-source tools, validate the affected source closure, and report the root cause, changed file, executed evidence, and remaining verification boundary.
""",
        public_fixture=case_root / "public",
        required_evidence=frozenset({"simulation"}),
        allowed_evidence=frozenset({"lint", "simulation", "waveform", "synthesis", "formal"}),
        grade=partial(_core_v_mcu_event_irq_grade, hidden=case_root / "private" / "soc_event_generator_hidden_tb.sv"),
    )
    return case, provenance


def _core_v_mcu_event_irq_grade(
    workspace: Path,
    run_root: Path,
    initial: Mapping[str, str],
    *,
    hidden: Path,
) -> dict[str, Any]:
    target_relative = CORE_V_MCU_EVENT_IRQ.affected_path
    target = workspace / target_relative
    rtl_root = target.parent
    generic_fifo = workspace / "rtl/vendor/pulp_platform_common_cells/src/deprecated/generic_fifo.sv"
    sources = [
        generic_fifo,
        rtl_root / "soc_event_queue.sv",
        rtl_root / "soc_event_arbiter.sv",
        target,
    ]
    if not all(_regular_file(path) for path in (*sources, hidden)):
        return {"correct": False, "error": "required_soc_source_or_hidden_test_missing"}
    evidence_root = run_root / "grader-evidence"
    manifest = CompileManifest.create(sources, "soc_event_generator", defines=["PULP_FPGA_EMUL"])
    lint = run_verilator_lint(manifest, artifact_root=evidence_root / "lint")
    simulation = run_iverilog_simulation(
        CompileManifest.create([*sources, hidden], "soc_event_generator_tb", defines=["PULP_FPGA_EMUL"]),
        artifact_root=evidence_root / "simulation",
    )
    target_hash = hash_file(target)
    changed, git_status = _git_state(workspace)
    protected = changed == [target_relative]
    source_changed = target_hash != initial.get(target_relative)
    statuses = {"lint": lint["status"], "simulation": simulation["status"]}
    return {
        "correct": statuses["simulation"] == "pass" and protected and source_changed,
        "grader_statuses": statuses,
        "non_gating_checks": {
            "lint": "reported but not correctness-gating because the pinned upstream closure has baseline warnings"
        },
        "candidate_hashes": {target_relative: target_hash},
        "source_changed": source_changed,
        "protected_files_unchanged": protected,
        "tracked_changed_files": changed,
        "git_status": git_status,
        "expected_agent_evidence_subjects": {"lint": [target_hash], "simulation": [target_hash]},
        "evidence": _evidence_view([lint, simulation]),
    }
