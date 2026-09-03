from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

from rtl_ass.errors import RtlAssError
from rtl_ass.integrity import hash_file
from rtl_ass.waveform import query_waveform, validate_waveform_evidence
from rtl_ass.workflow import (
    load_verification_plan,
    summarize_verification_plan,
    validate_verification_plan,
    verification_execution_lock,
)

ROOT = Path(__file__).resolve().parents[1]


def _plan() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "plan_id": "focused-repair",
        "task_class": "debugging",
        "claims": [
            {
                "id": "regression",
                "statement": "The supplied self-checking regression passes.",
                "evidence_kind": "simulation",
                "requirement": "required",
                "expected_status": "pass",
            },
            {
                "id": "first-divergence",
                "statement": "The expected and actual signals have a localized first divergence.",
                "evidence_kind": "waveform",
                "requirement": "optional",
                "expected_status": "found",
            },
        ],
        "stop_policy": {"max_retries_per_claim": 0, "max_parallel_eda": 1},
    }


def _write_run_evidence(root: Path, name: str, *, input_hash: str = "a" * 64) -> Path:
    source = root / "dut.sv"
    artifact = root / f"{name}.log"
    source.write_text("module dut; endmodule\n", encoding="utf-8")
    artifact.write_text("PASS\n", encoding="utf-8")
    destination = root / f"{name}.json"
    evidence = {
        "schema_version": "1.0",
        "kind": "simulation",
        "status": "pass",
        "tool": {"name": "fixture", "version": "1"},
        "input_hash": input_hash,
        "subject_hashes": [{"index": 0, "path": source.as_posix(), "content_hash": hash_file(source)}],
        "top": "dut",
        "commands": [["fixture", "simulate"]],
        "artifacts": [artifact.as_posix()],
        "artifact_hashes": [{"index": 0, "path": artifact.as_posix(), "content_hash": hash_file(artifact)}],
        "evidence_file": destination.as_posix(),
        "started_at": "2026-09-03T00:00:00+00:00",
        "finished_at": "2026-09-03T00:00:01+00:00",
        "summary": {"fixture": True},
        "claim_scope": "tool execution evidence only",
    }
    destination.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return destination


class VerificationPlanTests(unittest.TestCase):
    def test_plan_validation_is_strict_and_hash_stable(self) -> None:
        first = validate_verification_plan(_plan())
        second = validate_verification_plan(_plan())
        self.assertEqual(first.plan_hash, second.plan_hash)
        self.assertEqual(first.summary()["required_claims"], ["regression"])

        invalid = _plan()
        invalid["claims"] = [dict(invalid["claims"][0]), dict(invalid["claims"][0])]
        with self.assertRaises(RtlAssError) as caught:
            validate_verification_plan(invalid)
        self.assertEqual(caught.exception.code, "invalid_verification_plan")

    def test_plan_file_rejects_symlinks_and_invalid_status_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(_plan()), encoding="utf-8")
            self.assertEqual(load_verification_plan(plan_path).value["plan_id"], "focused-repair")
            link = root / "plan-link.json"
            link.symlink_to(plan_path)
            with self.assertRaises(RtlAssError) as caught:
                load_verification_plan(link)
            self.assertEqual(caught.exception.code, "invalid_input_file")

            invalid = _plan()
            invalid["claims"][0]["expected_status"] = "fail"
            with self.assertRaises(RtlAssError):
                validate_verification_plan(invalid)

    def test_summary_revalidates_current_evidence_and_detects_redundant_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = _write_run_evidence(root, "first")
            second = _write_run_evidence(root, "second")
            plan = validate_verification_plan(_plan())
            summary = summarize_verification_plan(
                plan,
                [f"regression={first}", f"regression={second}"],
            )
            self.assertTrue(summary["ready_to_stop"])
            self.assertEqual(summary["retry_budget_exceeded_claims"], ["regression"])
            self.assertEqual(len(summary["duplicate_evidence_identities"]), 1)
            self.assertEqual(summary["claims"][0]["attempt_count"], 2)

            artifact = root / "second.log"
            artifact.write_text("changed\n", encoding="utf-8")
            with self.assertRaises(RtlAssError) as caught:
                summarize_verification_plan(plan, [f"regression={second}"])
            self.assertEqual(caught.exception.code, "evidence_artifact_changed")

    def test_optional_missing_evidence_does_not_prevent_stopping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = _write_run_evidence(root, "passing")
            summary = summarize_verification_plan(
                validate_verification_plan(_plan()),
                [f"regression={evidence}"],
            )
            self.assertTrue(summary["ready_to_stop"])
            self.assertEqual(summary["missing_required_claims"], [])
            self.assertEqual(summary["claims"][1]["status"], "missing")


class WorkflowLockTests(unittest.TestCase):
    def test_workspace_lock_blocks_concurrency_and_releases_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with verification_execution_lock(0, workspace=root) as lock_path:
                self.assertEqual(lock_path.read_text(encoding="ascii"), f"pid={os.getpid()}\n")
                with self.assertRaises(RtlAssError) as caught:
                    with verification_execution_lock(0, workspace=root):
                        self.fail("a second execution acquired the same workspace lock")
                self.assertEqual(caught.exception.code, "verification_busy")
                self.assertEqual(lock_path.read_text(encoding="ascii"), f"pid={os.getpid()}\n")
            with verification_execution_lock(0, workspace=root):
                pass
            self.assertEqual(lock_path.read_text(encoding="ascii"), "")

    def test_workspace_lock_rejects_symlinked_state_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as target:
            root = Path(temporary)
            (root / ".rtl-ass").symlink_to(target, target_is_directory=True)
            with self.assertRaises(RtlAssError) as caught:
                with verification_execution_lock(0, workspace=root):
                    self.fail("symlinked lock state was accepted")
            self.assertEqual(caught.exception.code, "verification_lock_unavailable")


class WaveformEvidenceValidationTests(unittest.TestCase):
    def test_real_waveform_result_is_current_and_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            waveform = Path(temporary) / "divergence.vcd"
            waveform.write_bytes((ROOT / "tests" / "fixtures" / "divergence.vcd").read_bytes())
            result = query_waveform(waveform, patterns=["expected"], max_events=100)
            validated = validate_waveform_evidence(result, require_current_waveform=True)
            self.assertEqual(validated["status"], "complete")
            waveform.write_text("changed\n", encoding="utf-8")
            with self.assertRaises(RtlAssError) as caught:
                validate_waveform_evidence(result, require_current_waveform=True)
            self.assertEqual(caught.exception.code, "waveform_evidence_changed")

    def test_inconsistent_event_count_is_rejected(self) -> None:
        result = query_waveform(ROOT / "tests" / "fixtures" / "divergence.vcd", patterns=["expected"])
        result["event_count"] += 1
        with self.assertRaises(RtlAssError) as caught:
            validate_waveform_evidence(result)
        self.assertEqual(caught.exception.code, "invalid_waveform_evidence")

    def test_forged_query_and_divergence_payloads_are_rejected(self) -> None:
        query = query_waveform(ROOT / "tests" / "fixtures" / "divergence.vcd", patterns=["expected"])
        query["events"][0]["signal"] = "unselected.signal"
        with self.assertRaises(RtlAssError):
            validate_waveform_evidence(query)

        divergence = query_waveform(ROOT / "tests" / "fixtures" / "divergence.vcd", patterns=["expected"])
        divergence = {
            "schema_version": "1.0",
            "kind": "vcd-first-divergence",
            "status": "found",
            "waveform": divergence["waveform"],
            "waveform_hash": divergence["waveform_hash"],
            "timescale": divergence["timescale"],
            "window": divergence["window"],
            "first_divergence": {},
        }
        with self.assertRaises(RtlAssError):
            validate_waveform_evidence(divergence, require_current_waveform=True)

    def test_fst_conversion_hashes_require_lowercase_sha256(self) -> None:
        result = query_waveform(ROOT / "tests" / "fixtures" / "divergence.vcd", patterns=["expected"])
        result["kind"] = "fst-query"
        result["conversion"] = {
            "tool": {"name": "fst2vcd", "binary_hash": "a" * 64},
            "command": ["fst2vcd", "trace.fst", "trace.vcd"],
            "converted_vcd_hash": "b" * 64,
            "timeout_seconds": 60,
            "max_converted_bytes": 1024,
        }
        validate_waveform_evidence(result)

        for field in ("binary_hash", "converted_vcd_hash"):
            tampered = json.loads(json.dumps(result))
            if field == "binary_hash":
                tampered["conversion"]["tool"][field] = "G" * 64
            else:
                tampered["conversion"][field] = "G" * 64
            with self.subTest(field=field), self.assertRaises(RtlAssError):
                validate_waveform_evidence(tampered)


if __name__ == "__main__":
    unittest.main()
