from __future__ import annotations

import unittest
from typing import Any, cast
from unittest import mock

from rtl_ass.tools import TOOLS, discover_tools


class ToolInventoryTests(unittest.TestCase):
    def test_inventory_separates_fallback_adapters_from_discovery_only_tools(self) -> None:
        report = cast(Any, discover_tools())
        by_name = {item["name"]: item for item in report["tools"]}

        self.assertEqual(report["tool_count"], len(TOOLS))
        self.assertEqual(
            {name for name, item in by_name.items() if item["integration"] == "discovery-only"},
            {"bwave", "gtkwave", "openroad", "slang", "surelog", "verible"},
        )
        self.assertEqual(
            {name for name, item in by_name.items() if item["integration"] == "fallback-adapter"},
            {
                "bitwuzla",
                "boolector",
                "cvc5",
                "eqy",
                "fst2vcd",
                "iverilog",
                "opensta",
                "symbiyosys",
                "verilator",
                "vvp",
                "yices",
                "yosys",
                "z3",
            },
        )

    def test_inventory_exposes_the_fallback_authorization_contract_without_execution(self) -> None:
        with mock.patch("rtl_ass.tools.shutil.which", return_value=None):
            report = cast(Any, discover_tools())

        self.assertEqual(report["available_count"], 0)
        self.assertEqual(
            report["usage_policy"],
            {
                "precedence": ["user-selected-flow", "project-local-flow", "rtl-ass-fallback-adapter"],
                "fallback_requires": [
                    "verification-required",
                    "no-user-selected-flow",
                    "no-usable-or-permitted-project-local-flow",
                    "user-confirmed-local-flow-boundary",
                    "user-confirmed-named-adapter",
                ],
            },
        )
        self.assertIn("no verification action was executed", report["claim"])


if __name__ == "__main__":
    unittest.main()
