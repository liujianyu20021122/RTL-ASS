"""Stable public facade for bounded open-source RTL evidence adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rtl_ass.compile_manifest import CompileInput, CompileManifest
from rtl_ass.errors import RtlAssError
from rtl_ass.evidence_common import (
    EquivalenceInputBundle,
    FormalInputBundle,
    SourceBundle,
    StaInputBundle,
    SynthesisInputBundle,
)
from rtl_ass.evidence_drivers import run_eqy_equivalence, run_symbiyosys_formal
from rtl_ass.evidence_sim import run_iverilog_simulation, run_verilator_lint, run_verilator_simulation
from rtl_ass.evidence_sta import run_opensta
from rtl_ass.evidence_yosys import run_yosys_equivalence, run_yosys_formal, run_yosys_synthesis

__all__ = [
    "CompileManifest",
    "EquivalenceInputBundle",
    "FormalInputBundle",
    "SourceBundle",
    "StaInputBundle",
    "SynthesisInputBundle",
    "run_equivalence_evidence",
    "run_eqy_equivalence",
    "run_formal_evidence",
    "run_iverilog_simulation",
    "run_opensta",
    "run_simulation_evidence",
    "run_symbiyosys_formal",
    "run_verilator_lint",
    "run_verilator_simulation",
    "run_yosys_equivalence",
    "run_yosys_formal",
    "run_yosys_synthesis",
]


def run_simulation_evidence(
    sources: CompileInput,
    *,
    backend: str,
    top: str | None = None,
    artifact_root: str | Path,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Dispatch a simulation through the audited backend boundary."""

    adapters = {
        "iverilog": run_iverilog_simulation,
        "verilator": run_verilator_simulation,
    }
    try:
        adapter = adapters[backend]
    except KeyError as exc:
        raise RtlAssError(
            "unsupported_evidence_backend", "unsupported simulation backend", {"backend": backend}
        ) from exc
    return adapter(sources, top=top, artifact_root=artifact_root, timeout_seconds=timeout_seconds)


def run_formal_evidence(
    sources: CompileInput,
    *,
    backend: str,
    depth: int,
    initialization: str,
    top: str | None = None,
    artifact_root: str | Path,
    timeout_seconds: int = 120,
    solver: str = "z3",
) -> dict[str, Any]:
    """Dispatch bounded assertion evidence without changing claim semantics."""

    if backend == "yosys":
        return run_yosys_formal(
            sources,
            top=top,
            depth=depth,
            initialization=initialization,
            artifact_root=artifact_root,
            timeout_seconds=timeout_seconds,
        )
    if backend == "sby":
        return run_symbiyosys_formal(
            sources,
            top=top,
            depth=depth,
            initialization=initialization,
            artifact_root=artifact_root,
            timeout_seconds=timeout_seconds,
            solver=solver,
        )
    raise RtlAssError("unsupported_evidence_backend", "unsupported formal backend", {"backend": backend})


def run_equivalence_evidence(
    *,
    reference_sources: CompileInput,
    implementation_sources: CompileInput,
    backend: str,
    depth: int,
    reference_top: str | None = None,
    implementation_top: str | None = None,
    initialization: str = "none",
    input_domain: str = "defined",
    artifact_root: str | Path,
    timeout_seconds: int = 120,
    solver: str = "z3",
) -> dict[str, Any]:
    """Dispatch equivalence evidence while preserving the shared contract."""

    if backend == "yosys":
        return run_yosys_equivalence(
            reference_sources=reference_sources,
            implementation_sources=implementation_sources,
            reference_top=reference_top,
            implementation_top=implementation_top,
            depth=depth,
            initialization=initialization,
            input_domain=input_domain,
            artifact_root=artifact_root,
            timeout_seconds=timeout_seconds,
        )
    if backend == "eqy":
        return run_eqy_equivalence(
            reference_sources=reference_sources,
            implementation_sources=implementation_sources,
            reference_top=reference_top,
            implementation_top=implementation_top,
            depth=depth,
            initialization=initialization,
            input_domain=input_domain,
            artifact_root=artifact_root,
            timeout_seconds=timeout_seconds,
            solver=solver,
        )
    raise RtlAssError("unsupported_evidence_backend", "unsupported equivalence backend", {"backend": backend})
