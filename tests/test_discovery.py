import ast
from contextlib import redirect_stdout, redirect_stderr
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from canary.discover import main
from canary.discovery import align_samples, discover_signal, pearson
from canary.observation import Frame, read_csv
from canary.reference import read_reference

ROOT = Path(__file__).resolve().parent.parent


class DiscoveryTests(unittest.TestCase):
    def parse(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reference.csv"
            path.write_text(text, encoding="utf-8")
            return read_reference(path, "measurement")

    def test_valid_reference(self):
        self.assertEqual(self.parse("measurement,extra,timestamp\n2,x,0\n3,y,0.1\n"),
                         [(0, 2), (0.1, 3)])
        self.assertEqual(self.parse("timestamp,measurement\n"), [])

    def test_malformed_reference(self):
        for text in ("", "timestamp,wrong\n", "timestamp,measurement,measurement\n"):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "header"):
                self.parse(text)
        for row in ("nan,2", "inf,2", "bad,2", "0,nan", "0,inf", "0,bad", "0", "0,1,2", ""):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, "line 2"):
                self.parse("timestamp,measurement\n" + row + "\n")
        for row in ("0,2", "-1,2"):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, "strictly increasing"):
                self.parse("timestamp,measurement\n0,1\n" + row)
        with self.assertRaisesRegex(ValueError, "malformed CSV"):
            self.parse('timestamp,measurement\n0,"unfinished')

    def test_timestamp_alignment(self):
        reference = [(0, 10), (1, 20), (2, 30), (3, 40)]
        self.assertEqual(align_samples([(3, 4), (0, 1), (2, 3), (9, 5)], reference),
                         ([1, 3, 4], [10, 30, 40]))
        self.assertEqual(align_samples([(0.01, 1), (2.01, 3)], reference, tolerance=0.02),
                         ([1, 3], [10, 30]))
        self.assertEqual(align_samples([(0.01, 1)], reference), ([], []))
        self.assertEqual(align_samples([(0.5, 1), (0.5, 2)], reference, tolerance=0.5),
                         ([1, 2], [10, 20]))
        self.assertEqual(align_samples([(0, 1), (0, 2)], reference), ([1], [10]))
        self.assertEqual(align_samples([(0, 1)], []), ([], []))
        with self.assertRaises(ValueError):
            align_samples([], reference, tolerance=-1)
        with self.assertRaises(ValueError):
            align_samples([], [(1, 1), (0, 0)])

    def test_pearson_known_sequences(self):
        self.assertAlmostEqual(pearson([1, 2, 3], [5, 7, 9]), 1)
        self.assertAlmostEqual(pearson([1, 2, 3], [9, 7, 5]), -1)
        self.assertAlmostEqual(pearson([-1, 0, 1], [1, -2, 1]), 0)
        self.assertAlmostEqual(pearson([1, 2, 3, 4], [1, 3, 2, 4]), 0.8)
        self.assertAlmostEqual(pearson([-1e308, 0, 1e308], [1, 2, 3]), 1)

    def test_constant_and_insufficient_series(self):
        self.assertIsNone(pearson([1, 1, 1], [1, 2, 3]))
        self.assertIsNone(pearson([1, 2, 3], [0, 0, 0]))
        self.assertIsNone(pearson([1, 2], [1, 2]))
        self.assertIsNone(pearson([], []))
        for xs, ys in (([1], []), ([1, 2, float("nan")], [1, 2, 3])):
            with self.assertRaises(ValueError):
                pearson(xs, ys)
        with self.assertRaises(ValueError):
            pearson([], [], min_samples=2)

    def test_ranking_preserves_negative_and_breaks_ties(self):
        values = [1, 4, 2, 7]
        frames = [Frame(i, can_id, bytes([10 - v]) + bytes(7))
                  for can_id in (9, 3) for i, v in enumerate(values)]
        reference = list(enumerate(values))
        results = discover_signal(frames, reference)
        self.assertEqual([(r.can_id, r.byte_offset, r.width_bits) for r in results],
                         [(can_id, 0, width) for can_id in (3, 9) for width in (8, 8, 16, 16, 16, 16)])
        self.assertTrue(all(abs(r.correlation + 1) < 1e-12 and r.aligned_samples == 4 for r in results))
        self.assertEqual(results, discover_signal(list(reversed(frames)), reference))
        self.assertEqual(discover_signal(frames, [(100, 1), (101, 2), (102, 3)]), [])
        self.assertEqual(discover_signal(frames, [(i, 0) for i in range(4)]), [])

    def test_end_to_end_synthetic(self):
        from simulator.ground_truth import SPEED

        frames = read_csv(ROOT / "datasets/synthetic/can_log.csv")
        reference = read_reference(ROOT / "datasets/synthetic/speed_reference.csv", "speed_kph")
        results = discover_signal(frames, reference)
        self.assertEqual(len(results), 264)
        top = results[0]
        self.assertEqual((top.can_id, top.byte_offset, top.width_bits),
                         (SPEED.can_id, SPEED.start_byte, SPEED.width * 8))
        self.assertGreater(top.correlation, 0.999999)
        self.assertEqual(top.aligned_samples, 6000)
        self.assertEqual(top.endian, "little")
        self.assertFalse(top.signed)
        self.assertEqual(results, sorted(results, key=lambda r: (-abs(r.correlation), r.can_id,
                                                                 r.byte_offset, r.width_bits)))

    def test_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            can_path, ref_path = Path(directory) / "can.csv", Path(directory) / "ref.csv"
            can_path.write_text("timestamp,can_id,data\n" + "".join(
                f"{i},1,{i + 1:02X} 00 00 00 00 00 00 00\n" for i in range(3)), encoding="utf-8")
            ref_path.write_text("timestamp,measurement\n0,1\n1,2\n2,3\n", encoding="utf-8")
            args = ["canary.discover", str(can_path), str(ref_path), "--value-column", "measurement", "--top", "1"]
            output = io.StringIO()
            with patch("sys.argv", args), redirect_stdout(output):
                main()
            self.assertIn("Reference: measurement", output.getvalue())
            self.assertIn("Candidates searched: 44", output.getvalue())
            self.assertIn("Samples:      3", output.getvalue())
            self.assertNotIn("#2", output.getvalue())
            with patch("sys.argv", args + ["--tolerance", "nan"]), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    main()
            self.assertEqual(raised.exception.code, 2)

    def test_production_dependencies(self):
        allowed = {"argparse", "bisect", "collections", "csv", "dataclasses", "html", "json", "math", "pathlib", "re"}
        local = {p.stem for p in (ROOT / "canary").glob("*.py")} | {"llm"}
        for path in (ROOT / "canary").glob("*.py"):
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                for forbidden in ("simulator", "ground_truth", "datasets/", "speed_kph", "importlib", "__import__"):
                    self.assertNotIn(forbidden, source)
                for node in ast.walk(ast.parse(source)):
                    if isinstance(node, ast.Import):
                        self.assertTrue(all(a.name.split(".")[0] in allowed for a in node.names))
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            self.assertIn(node.module.split(".")[0], local if node.level else allowed)


if __name__ == "__main__":
    unittest.main()
