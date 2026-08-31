from __future__ import annotations

import json
import unittest
from pathlib import Path

from evals.validate_cases import validate_manifest

ROOT = Path(__file__).resolve().parents[1]


class EvaluationManifestTests(unittest.TestCase):
    def test_public_manifest_is_valid_and_explicitly_unscored(self) -> None:
        manifest = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))
        validated = validate_manifest(manifest)
        self.assertEqual(validated["effectiveness_status"], "not_evaluated")
        self.assertEqual(len(validated["cases"]), 6)


if __name__ == "__main__":
    unittest.main()
