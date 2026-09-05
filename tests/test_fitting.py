import csv
from contextlib import redirect_stdout, redirect_stderr
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from canary.discover import main
from canary.discovery import discover_signal
from canary.fitting import discover_and_fit, fit_linear, reconstruct, reconstruction_metrics, write_reconstruction
from canary.observation import Frame, read_csv
from canary.reference import read_reference

ROOT = Path(__file__).resolve().parent.parent


class FittingTests(unittest.TestCase):
    def test_exact_linear(self):
        fit = fit_linear([0, 1, 2, 3], [0, 2, 4, 6])
        self.assertEqual((fit.scale, fit.offset, fit.rmse, fit.mae, fit.r_squared), (2, 0, 0, 0, 1))
        self.assertEqual(reconstruct([0, 1, 2], fit.scale, fit.offset), [0, 2, 4])

    def test_nonzero_offset_and_negative_scale(self):
        fit = fit_linear([0, 1, 2, 3], [7, 5, 3, 1])
        self.assertEqual((fit.scale, fit.offset), (-2, 7))
        self.assertEqual(fit.rmse, 0)

    def test_noisy_linear(self):
        # Noise [1,-2,1] has zero mean and zero covariance with x.
        fit = fit_linear([0, 1, 2], [6, 5, 10])
        self.assertAlmostEqual(fit.scale, 2)
        self.assertAlmostEqual(fit.offset, 5)
        self.assertAlmostEqual(fit.rmse, 2 ** 0.5)
        self.assertAlmostEqual(fit.mae, 4 / 3)
        self.assertAlmostEqual(fit.r_squared, 4 / 7)

    def test_constant_and_insufficient(self):
        self.assertIsNone(fit_linear([2, 2, 2], [1, 2, 3]))
        self.assertIsNone(fit_linear([], []))
        self.assertIsNone(fit_linear([1, 2], [3, 4]))
        fit = fit_linear([0, 1, 2], [7, 7, 7])
        self.assertEqual((fit.scale, fit.offset, fit.rmse), (0, 7, 0))
        self.assertIsNone(fit.r_squared)

    def test_invalid_inputs(self):
        for xs, ys in (([1], []), ([0, float("nan"), 2], [1, 2, 3]),
                       ([0, 1, 2], [1, float("inf"), 3])):
            with self.subTest(xs=xs, ys=ys), self.assertRaises(ValueError):
                fit_linear(xs, ys)
        with self.assertRaises(ValueError):
            fit_linear([], [], min_samples=2)
        with self.assertRaises(ValueError):
            reconstruct([1], float("inf"), 0)
        with self.assertRaises(ValueError):
            reconstruct([1e308], 1e308, 0)
        with self.assertRaises(ValueError):
            reconstruction_metrics([], [])
        with self.assertRaises(ValueError):
            discover_and_fit([], [], top_n=0)

    def test_metrics(self):
        metrics = reconstruction_metrics([1, 2, 3], [2, 2, 1])
        self.assertAlmostEqual(metrics.rmse, (5 / 3) ** 0.5)
        self.assertEqual(metrics.mae, 1)
        self.assertEqual(metrics.r_squared, -1.5)
        self.assertIsNone(reconstruction_metrics([2, 2, 2], [0, 0, 0]).r_squared)

    def test_alignment_export_and_ranking(self):
        frames = [Frame(t, 5, bytes([v]) + bytes(7)) for t, v in ((2.01, 3), (0.01, 1), (1.01, 2), (9, 99))]
        reference = [(0, 7), (1, 9), (2, 11)]
        results = discover_and_fit(frames, reference, top_n=1, tolerance=0.02)
        ranked = discover_signal(frames, reference, tolerance=0.02)
        self.assertEqual((results[0].can_id, results[0].byte_offset, results[0].width_bits),
                         (ranked[0].can_id, ranked[0].byte_offset, ranked[0].width_bits))
        self.assertEqual((results[0].scale, results[0].offset), (2, 5))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "reconstructed.csv"
            write_reconstruction(path, frames, reference, results[0], tolerance=0.02)
            with path.open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(reader.fieldnames, ["timestamp", "reference", "reconstructed", "raw"])
                rows = list(reader)
            self.assertEqual([float(r["timestamp"]) for r in rows], [0.01, 1.01, 2.01])
            self.assertEqual([float(r["raw"]) for r in rows], [1, 2, 3])
            self.assertTrue(all(float(r["reference"]) == float(r["reconstructed"]) for r in rows))

    def test_end_to_end_synthetic(self):
        from simulator.ground_truth import SPEED

        frames = read_csv(ROOT / "datasets/synthetic/can_log.csv")
        reference = read_reference(ROOT / "datasets/synthetic/speed_reference.csv", "speed_kph")
        results = discover_and_fit(frames, reference, top_n=10)
        self.assertEqual(len(results), 10)
        top = results[0]
        self.assertEqual((top.can_id, top.byte_offset, top.width_bits),
                         (SPEED.can_id, SPEED.start_byte, SPEED.width * 8))
        self.assertAlmostEqual(top.scale, SPEED.scale, delta=1e-7)
        self.assertAlmostEqual(top.offset, SPEED.offset, delta=0.001)
        self.assertLess(top.rmse, SPEED.scale / 2)
        self.assertLess(top.mae, SPEED.scale / 2)
        self.assertGreater(top.r_squared, 0.999999)
        self.assertEqual(top.aligned_samples, 6000)
        self.assertAlmostEqual(top.r_squared, top.correlation ** 2, places=12)

    def test_cli_fit_and_export(self):
        with tempfile.TemporaryDirectory() as directory:
            can_path, ref_path, output = [Path(directory) / name for name in ("can.csv", "ref.csv", "out.csv")]
            can_path.write_text("timestamp,can_id,data\n" + "".join(
                f"{i},1,{i:02X} 00 00 00 00 00 00 00\n" for i in range(3)), encoding="utf-8")
            ref_path.write_text("timestamp,value\n0,5\n1,7\n2,9\n", encoding="utf-8")
            args = ["canary.discover", str(can_path), str(ref_path), "--value-column", "value", "--top", "1"]
            text = io.StringIO()
            with patch("sys.argv", args + ["--fit", "--output-reconstruction", str(output)]), redirect_stdout(text):
                main()
            self.assertIn("Scale:        2", text.getvalue())
            self.assertIn("Offset:       5", text.getvalue())
            self.assertIn("R-squared:    1", text.getvalue())
            self.assertEqual(len(output.read_text().splitlines()), 4)
            for extra in (["--output-reconstruction", str(output)],
                          ["--fit", "--output-reconstruction", str(can_path)]):
                with patch("sys.argv", args + extra), redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        main()
                self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
