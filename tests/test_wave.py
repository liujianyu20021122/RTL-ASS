from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rtl_ass.errors import RtlAssError
from rtl_ass.wave import first_divergence_vcd, query_vcd
from rtl_ass.waveform import first_divergence_waveform, query_waveform

FIXTURE = Path(__file__).parent / "fixtures" / "divergence.vcd"


class WaveTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("vcd2fst") and shutil.which("fst2vcd"), "GTKWave FST converters are unavailable")
    def test_fst_query_and_divergence_bind_original_and_conversion_hashes(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            fst_path = Path(temporary_directory) / "divergence.fst"
            conversion = subprocess.run(
                [shutil.which("vcd2fst"), str(FIXTURE), str(fst_path)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(conversion.returncode, 0, conversion.stderr)
            query = query_waveform(fst_path, patterns=("tb.actual",))
            divergence = first_divergence_waveform(
                fst_path,
                expected="tb.expected",
                actual="tb.actual",
            )
        self.assertEqual(query["kind"], "fst-query")
        self.assertGreaterEqual(query["event_count"], 3)
        self.assertEqual(len(query["waveform_hash"]), 64)
        self.assertEqual(len(query["conversion"]["tool"]["binary_hash"]), 64)
        self.assertEqual(len(query["conversion"]["converted_vcd_hash"]), 64)
        self.assertEqual(divergence["kind"], "fst-first-divergence")
        self.assertEqual(divergence["first_divergence"]["time"], 10)

    @unittest.skipUnless(shutil.which("vcd2fst") and shutil.which("fst2vcd"), "GTKWave FST converters are unavailable")
    def test_fst_conversion_enforces_strict_expansion_limit(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            fst_path = Path(temporary_directory) / "divergence.fst"
            subprocess.run(
                [shutil.which("vcd2fst"), str(FIXTURE), str(fst_path)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            with self.assertRaises(RtlAssError) as caught:
                query_waveform(fst_path, patterns=("tb.actual",), max_converted_bytes=10)
        self.assertEqual(caught.exception.code, "wave_conversion_too_large")

    def test_query_is_bounded_and_selective(self) -> None:
        result = query_vcd(FIXTURE, patterns=["tb.actual"], start_time=5, end_time=10, max_events=10)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["timescale"], "1ns")
        self.assertEqual(result["event_count"], 2)
        self.assertEqual({event["time"] for event in result["events"]}, {5, 10})

    def test_first_divergence_compares_after_all_same_time_updates(self) -> None:
        result = first_divergence_vcd(FIXTURE, expected="tb.expected", actual="tb.actual")
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["first_divergence"]["time"], 10)
        self.assertEqual(result["first_divergence"]["expected_value"], "0")
        self.assertEqual(result["first_divergence"]["actual_value"], "1")

    def test_truncated_query_does_not_claim_no_divergence(self) -> None:
        result = first_divergence_vcd(
            FIXTURE,
            expected="tb.expected",
            actual="tb.actual",
            max_events=2,
        )
        self.assertEqual(result["status"], "not_found_in_truncated_window")

    def test_diff_rejects_comparing_a_signal_with_itself(self) -> None:
        with self.assertRaises(RtlAssError) as caught:
            first_divergence_vcd(FIXTURE, expected="tb.expected", actual="tb.expected")
        self.assertEqual(caught.exception.code, "wave_diff_same_signal")

    def test_invalid_encoding_is_a_structured_error(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "invalid.vcd"
            path.write_bytes(b"$scope module top $end\n\xff")
            with self.assertRaises(RtlAssError) as caught:
                query_vcd(path, patterns=("top.*",))
        self.assertEqual(caught.exception.code, "invalid_vcd_encoding")

    def test_query_rejects_boolean_limits_and_invalid_patterns(self) -> None:
        cases = (
            ({"patterns": ("tb.actual",), "start_time": True}, "invalid_wave_window"),
            ({"patterns": ("tb.actual",), "end_time": True}, "invalid_wave_window"),
            ({"patterns": ("tb.actual",), "max_events": True}, "invalid_event_limit"),
            ({"patterns": ("",)}, "wave_signal_required"),
        )
        for arguments, code in cases:
            with self.subTest(code=code), self.assertRaises(RtlAssError) as caught:
                query_vcd(FIXTURE, **arguments)
            self.assertEqual(caught.exception.code, code)


if __name__ == "__main__":
    unittest.main()
