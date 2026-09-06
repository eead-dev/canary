from contextlib import redirect_stdout
from dataclasses import asdict
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from canary.alignment import AlignmentConfig, align_series
from canary.discover import main
from canary.discovery import align_samples, discover_signal
from canary.tools import analyze_candidate, fit_candidate
from canary.observation import Frame, read_csv
from canary.reference import read_reference
from simulator.challenges import generate_scenario


class AlignmentTests(unittest.TestCase):
    def test_exact_unchanged(self):
        candidate, reference = [(2, 3), (0, 1), (1, 2)], [(0, 5), (1, 7), (2, 9)]
        result = align_series(candidate, reference)
        self.assertEqual(result.rows, [(0, 1, 5), (1, 2, 7), (2, 3, 9)])
        self.assertEqual(align_samples(candidate, reference), ([1, 2, 3], [5, 7, 9]))
        self.assertEqual(align_series([(0.1, 1)], reference, AlignmentConfig("exact", 1)).rows, [])

    def test_nearest_and_diagnostics(self):
        result = align_series([(2.125, 3), (0.125, 1), (1.125, 2), (9, 4)],
                              [(0, 5), (1, 7), (2, 9), (3, 11)], AlignmentConfig("nearest", 0.125))
        self.assertEqual(result.rows, [(0.125, 1, 5), (1.125, 2, 7), (2.125, 3, 9)])
        self.assertEqual(asdict(result.diagnostics), {"candidate_sample_count": 4, "matched_sample_count": 3,
            "unmatched_sample_count": 1, "match_ratio": 0.75,
            "mean_absolute_timestamp_error": 0.125, "max_absolute_timestamp_error": 0.125})

    def test_tolerance_rejection(self):
        result = align_series([(0.25, 1)], [(0, 0), (1, 1)], AlignmentConfig("nearest", 0.2))
        self.assertEqual(result.rows, [])
        self.assertIsNone(result.diagnostics.mean_absolute_timestamp_error)
        self.assertEqual(result.diagnostics.match_ratio, 0)

    def test_ties_and_no_reference_reuse(self):
        result = align_series([(0.5, 10), (0.5, 20), (0.5, 30)], [(0, 1), (1, 2)], AlignmentConfig("nearest", 0.5))
        self.assertEqual(result.rows, [(0.5, 10, 1), (0.5, 20, 2)])
        self.assertEqual(result.diagnostics.unmatched_sample_count, 1)

    def test_no_extrapolation(self):
        result = align_series([(-0.01, 1), (1.01, 2)], [(0, 1), (1, 2)], AlignmentConfig("nearest", 0.1))
        self.assertEqual(result.rows, [])
        self.assertEqual(align_series([], []).diagnostics.candidate_sample_count, 0)
        self.assertEqual(align_series([(0, 1)], []).rows, [])

    def test_invalid_tolerances_and_mode(self):
        for tolerance in (-1, float("nan"), float("inf"), "0.02", None, True):
            with self.subTest(tolerance=tolerance), self.assertRaises(ValueError):
                AlignmentConfig("nearest", tolerance)
        with self.assertRaises(ValueError):
            AlignmentConfig("interpolate", 0.1)

    def test_tool_diagnostics_and_mode(self):
        frames = [Frame(t, 1, bytes([i]) + bytes(7)) for i, t in enumerate((0.125, 1.125, 2.125))]
        reference = [(i, i * 2 + 5) for i in range(4)]
        exact = analyze_candidate(frames, 1, 0, 8, reference, alignment="exact", tolerance=0.2)
        self.assertEqual(exact["alignment_diagnostics"]["matched_sample_count"], 0)
        nearest = analyze_candidate(frames, 1, 0, 8, reference, alignment="nearest", tolerance=0.2)
        fit = fit_candidate(frames, 1, 0, 8, reference, alignment="nearest", tolerance=0.2)
        self.assertEqual(nearest["alignment_diagnostics"], fit["alignment_diagnostics"])
        self.assertEqual(fit["fit"]["scale"], 2)
        json.dumps(nearest, allow_nan=False)

    def test_jittered_synthetic_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            path = generate_scenario("timestamp_jitter", Path(directory))
            frames = read_csv(path / "can_log.csv")
            reference = read_reference(path / "reference.csv", "value")
            self.assertEqual(discover_signal(frames, reference, alignment="exact"), [])
            results = discover_signal(frames, reference, alignment="nearest", tolerance=0.004)
            truth = json.loads((path / "ground_truth.json").read_text())["target"]
            best = results[0]
            self.assertEqual((best.can_id, best.byte_offset * 8, best.width_bits),
                             (truth["can_id"], truth["start_bit"], 15))
            self.assertTrue(any(c.width_bits == truth["width_bits"] and c.start_bit == truth["start_bit"]
                                for c in [best.equivalence.representative, *best.equivalence.equivalent_candidates]))
            self.assertGreater(best.correlation, 0.999999)
            diagnostic = best.alignment_diagnostics
            self.assertGreaterEqual(diagnostic.matched_sample_count, 5998)
            self.assertLessEqual(diagnostic.max_absolute_timestamp_error, 0.004)
            self.assertEqual(diagnostic.candidate_sample_count, 6000)

    def test_cli_alignment_options(self):
        with tempfile.TemporaryDirectory() as directory:
            can, ref = Path(directory) / "can.csv", Path(directory) / "ref.csv"
            can.write_text("timestamp,can_id,data\n" + "".join(
                f"{i+0.125},1,{i:02X} 00 00 00 00 00 00 00\n" for i in range(3)))
            ref.write_text("timestamp,value\n0,5\n1,7\n2,9\n3,11\n")
            output = io.StringIO()
            with patch("sys.argv", ["canary.discover", str(can), str(ref), "--value-column", "value",
                                      "--alignment", "nearest", "--timestamp-tolerance", "0.2", "--fit", "--top", "1"]), redirect_stdout(output):
                main()
            self.assertIn("3/3 matched", output.getvalue())
            self.assertIn("mean 0.125000000", output.getvalue())


if __name__ == "__main__":
    unittest.main()
