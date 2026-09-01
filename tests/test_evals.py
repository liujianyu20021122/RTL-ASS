from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from evals.run_codex_ab import _hash_files, _hash_tree
from evals.validate_cases import validate_manifest
from evals.workflow_cases import get_case

ROOT = Path(__file__).resolve().parents[1]


class EvaluationManifestTests(unittest.TestCase):
    def test_public_manifest_is_valid_and_explicitly_unscored(self) -> None:
        manifest = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))
        validated = validate_manifest(manifest)
        self.assertEqual(validated["effectiveness_status"], "not_evaluated")
        self.assertEqual(len(validated["cases"]), 6)

    def test_multitask_summary_is_internally_consistent(self) -> None:
        manifest = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))
        summary = json.loads(
            (ROOT / "evals" / "results" / "2026-09-01-codex-multitask-summary.json").read_text(encoding="utf-8")
        )
        cases = summary["cases"]
        self.assertEqual(summary["schema_version"], "1.0")
        self.assertEqual(
            summary["effectiveness_status"],
            "workflow_mechanism_validated_general_correctness_uplift_not_established",
        )
        self.assertEqual({case["id"] for case in cases}, {case["id"] for case in manifest["cases"]})
        self.assertEqual(len({case["report_hash"] for case in cases}), 6)

        aggregate = summary["aggregate_descriptive_only"]
        self.assertEqual(aggregate["runs_per_condition"], 30)
        for condition in ("off", "on"):
            expected = aggregate[condition]
            for field in (
                "candidate_correct",
                "task_successes",
                "deliverable_complete",
                "complete_structured_evidence",
                "observed_skill_use",
                "timeouts",
                "input_tokens",
                "output_tokens",
            ):
                self.assertEqual(sum(case[condition][field] for case in cases), expected[field], field)
            self.assertAlmostEqual(
                sum(case[condition]["duration_seconds"] for case in cases), expected["duration_seconds"], places=6
            )

        for digest in (*summary["identity"].values(), *(case["report_hash"] for case in cases)):
            self.assertEqual(len(digest), 64)
            int(digest, 16)

    def test_multitask_summary_preserves_audited_payload_and_current_inputs(self) -> None:
        summary = json.loads(
            (ROOT / "evals" / "results" / "2026-09-01-codex-multitask-summary.json").read_text(encoding="utf-8")
        )
        skill_hash = _hash_tree(ROOT / ".agents" / "skills" / "rtl-ass")
        identity = summary["identity"]
        self.assertEqual(
            identity["harness_hash"],
            _hash_files((ROOT / "evals" / "run_codex_ab.py", ROOT / "evals" / "workflow_cases.py")),
        )
        self.assertEqual(identity["skill_hash"], skill_hash)

        # This report is immutable evidence for the exact v1.0 runtime that was
        # evaluated. Package-version changes legitimately alter the current
        # runtime tree; they must not relabel an historical evaluation payload.
        self.assertEqual(identity["runtime_hash"], "acab6c1f573160c4209391a319170680059f33cc09675d25d1cd1606d72fd62d")
        self.assertEqual(
            identity["on_payload_hash"],
            hashlib.sha256(f"{identity['skill_hash']}:{identity['runtime_hash']}".encode()).hexdigest(),
        )
        for published in summary["cases"]:
            case = get_case(published["id"])
            self.assertEqual(published["prompt_hash"], hashlib.sha256(case.prompt.encode()).hexdigest())
            self.assertEqual(published["fixture_hash"], _hash_tree(case.public_fixture))
            self.assertEqual(published["hidden_grader_hash"], _hash_tree(case.public_fixture.parent / "private"))


if __name__ == "__main__":
    unittest.main()
