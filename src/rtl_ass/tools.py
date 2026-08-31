"""Discovery of optional open-source RTL tools."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    commands: tuple[str, ...]
    capability: str


TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition("verilator", ("verilator",), "lint-and-simulation"),
    ToolDefinition("iverilog", ("iverilog",), "simulation-compile"),
    ToolDefinition("vvp", ("vvp",), "simulation-runtime"),
    ToolDefinition("yosys", ("yosys",), "synthesis-and-formal"),
    ToolDefinition("opensta", ("sta", "opensta"), "static-timing-analysis"),
    ToolDefinition("symbiyosys", ("sby",), "formal-orchestration"),
    ToolDefinition("eqy", ("eqy",), "equivalence-checking"),
    ToolDefinition("slang", ("slang",), "systemverilog-frontend"),
    ToolDefinition("surelog", ("surelog",), "systemverilog-uhdm-frontend"),
    ToolDefinition("verible", ("verible-verilog-lint",), "systemverilog-lint"),
    ToolDefinition("gtkwave", ("gtkwave",), "waveform-gui"),
    ToolDefinition("fst2vcd", ("fst2vcd",), "fst-waveform-conversion"),
    ToolDefinition("bwave", ("bwave",), "waveform-query"),
    ToolDefinition("openroad", ("openroad",), "physical-implementation"),
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
                "status": "available" if resolved else "not_available",
                "path": resolved,
            }
        )
    available = sum(item["status"] == "available" for item in tools)
    return {
        "schema_version": "1.0",
        "available_count": available,
        "tool_count": len(tools),
        "tools": tools,
        "claim": "tool discovery only; no verification action was executed",
    }
