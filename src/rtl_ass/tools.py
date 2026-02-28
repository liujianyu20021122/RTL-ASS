"""Discovery of optional open-source RTL tools."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Iterable, Literal

ToolIntegration = Literal["fallback-adapter", "discovery-only"]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    commands: tuple[str, ...]
    capability: str
    integration: ToolIntegration


TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition("verilator", ("verilator",), "lint-and-simulation", "fallback-adapter"),
    ToolDefinition("iverilog", ("iverilog",), "simulation-compile", "fallback-adapter"),
    ToolDefinition("vvp", ("vvp",), "simulation-runtime", "fallback-adapter"),
    ToolDefinition("yosys", ("yosys",), "synthesis-and-formal", "fallback-adapter"),
    ToolDefinition("opensta", ("sta", "opensta"), "static-timing-analysis", "fallback-adapter"),
    ToolDefinition("symbiyosys", ("sby",), "formal-orchestration", "fallback-adapter"),
    ToolDefinition("eqy", ("eqy",), "equivalence-checking", "fallback-adapter"),
    ToolDefinition("z3", ("z3",), "formal-solver", "fallback-adapter"),
    ToolDefinition("boolector", ("boolector",), "formal-solver", "fallback-adapter"),
    ToolDefinition("bitwuzla", ("bitwuzla",), "formal-solver", "fallback-adapter"),
    ToolDefinition("cvc5", ("cvc5",), "formal-solver", "fallback-adapter"),
    ToolDefinition("yices", ("yices-smt2", "yices"), "formal-solver", "fallback-adapter"),
    ToolDefinition("fst2vcd", ("fst2vcd",), "fst-waveform-conversion", "fallback-adapter"),
    ToolDefinition("slang", ("slang",), "systemverilog-frontend", "discovery-only"),
    ToolDefinition("surelog", ("surelog",), "systemverilog-uhdm-frontend", "discovery-only"),
    ToolDefinition("verible", ("verible-verilog-lint",), "systemverilog-lint", "discovery-only"),
    ToolDefinition("gtkwave", ("gtkwave",), "waveform-gui", "discovery-only"),
    ToolDefinition("bwave", ("bwave",), "waveform-query", "discovery-only"),
    ToolDefinition("openroad", ("openroad",), "physical-implementation", "discovery-only"),
)


def discover_tools(definitions: Iterable[ToolDefinition] = TOOLS) -> dict[str, object]:
    tools = []
    for definition in definitions:
        resolved = None
        for command in definition.commands:
            resolved = shutil.which(command)
            if resolved is not None:
                break
        tools.append(
            {
                "name": definition.name,
                "capability": definition.capability,
                "integration": definition.integration,
                "status": "available" if resolved else "not_available",
                "path": resolved,
            }
        )
    available = sum(item["status"] == "available" for item in tools)
    fallback_adapters = sum(item["integration"] == "fallback-adapter" for item in tools)
    return {
        "schema_version": "1.0",
        "available_count": available,
        "fallback_adapter_count": fallback_adapters,
        "tool_count": len(tools),
        "tools": tools,
        "usage_policy": {
            "precedence": ["user-selected-flow", "project-local-flow", "rtl-ass-fallback-adapter"],
            "fallback_requires": [
                "verification-required",
                "no-user-selected-flow",
                "no-usable-or-permitted-project-local-flow",
                "user-confirmed-local-flow-boundary",
                "user-confirmed-named-adapter",
            ],
        },
        "claim": "tool inventory and discovery only; no verification action was executed",
    }
