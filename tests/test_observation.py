import ast
from contextlib import redirect_stdout, redirect_stderr
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from canary.inspect import main
from canary.observation import (
    Candidate, Frame, byte_aligned_candidates, extract_candidate, frame_counts,
    frames_for_id, read_csv, timestamp_bounds, unique_ids, update_frequencies,
)

ROOT = Path(__file__).resolve().parent.parent
HEADER = "timestamp,can_id,data\n"
PAYLOAD = "00 01 7F 80 FE FF 34 12"


class ObservationTests(unittest.TestCase):
    def parse(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "traffic.csv"
            path.write_text(text, encoding="utf-8")
            return read_csv(path)

    def test_successful_parsing(self):
        frames = self.parse(HEADER + f"0,0x123,{PAYLOAD}\n0.01,291,00017f80feff3412\n")
        self.assertEqual(frames, [Frame(0, 291, bytes.fromhex(PAYLOAD)),
                                  Frame(0.01, 291, bytes.fromhex(PAYLOAD))])
        reordered = self.parse("data,can_id,timestamp,extra\n" + f"{PAYLOAD},0X7FF,1,ignored\n")
        self.assertEqual(reordered[0].can_id, 2047)

    def test_malformed_ids(self):
        for value in ("-1", "2048", "0x800", "0x", "xyz", "1.5", "", "1A4"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "line 2: CAN ID"):
                self.parse(HEADER + f"0,{value},{PAYLOAD}\n")

    def test_malformed_payloads(self):
        for value in ("GG" * 8, "0" * 15, "00 " * 7, "00 " * 9, "", "0x" + "00" * 8):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "line 2: payload"):
                self.parse(HEADER + f"0,1,{value}\n")

    def test_malformed_timestamps(self):
        for value in ("nan", "inf", "-inf", "1e999", "bad", ""):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "line 2: timestamp"):
                self.parse(HEADER + f"{value},1,{PAYLOAD}\n")

    def test_malformed_structure(self):
        for text in ("", "timestamp,can_id\n", "timestamp,can_id,data,data\n"):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "header"):
                self.parse(text)
        for row in ("0,1\n", f"0,1,{PAYLOAD},extra\n", "\n"):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, "line 2: expected"):
                self.parse(HEADER + row)
        with self.assertRaisesRegex(ValueError, "malformed CSV"):
            self.parse(HEADER + '0,1,"unterminated')

    def test_frame_invariants(self):
        for timestamp, can_id, data in ((float("nan"), 1, bytes(8)),
                                       (0, 2048, bytes(8)), (0, 1, bytes(7)),
                                       (0, 1, bytearray(8))):
            with self.subTest(can_id=can_id, data=data), self.assertRaises(ValueError):
                Frame(timestamp, can_id, data)

    def test_counts_unique_ids_selection_and_bounds(self):
        frames = [Frame(2, 7, bytes(8)), Frame(0, 3, bytes(8)), Frame(1, 7, bytes(8))]
        self.assertEqual(frame_counts(frames), {3: 1, 7: 2})
        self.assertEqual(unique_ids(frames), [3, 7])
        self.assertEqual(timestamp_bounds(frames), (0, 2))
        self.assertEqual(frames_for_id(frames, 7), [frames[0], frames[2]])
        self.assertEqual(frames_for_id(frames, 8), [])
        self.assertEqual(unique_ids([]), [])
        self.assertEqual(frame_counts([]), {})
        self.assertIsNone(timestamp_bounds([]))

    def test_frequency_estimation(self):
        frames = [Frame(t, 1, bytes(8)) for t in (0.03, 0, 0.01)]
        frames += [Frame(1, 2, bytes(8)), Frame(2, 3, bytes(8)), Frame(2, 3, bytes(8))]
        frequencies = update_frequencies(frames)
        self.assertAlmostEqual(frequencies[1], 2 / 0.03)
        self.assertIsNone(frequencies[2])
        self.assertIsNone(frequencies[3])
        self.assertEqual(update_frequencies([]), {})

    def test_all_8_bit_candidates(self):
        frames = [Frame(1, 5, bytes.fromhex(PAYLOAD)), Frame(2, 6, bytes(8)),
                  Frame(3, 5, bytes([255] * 8))]
        for offset, expected in enumerate((0, 1, 127, 128, 254, 255, 52, 18)):
            with self.subTest(offset=offset):
                self.assertEqual(extract_candidate(frames, 5, Candidate(offset, 8)),
                                 [(1, expected), (3, 255)])

    def test_all_16_bit_little_endian_candidates(self):
        frames = [Frame(1, 5, bytes.fromhex(PAYLOAD))]
        for offset, expected in enumerate((0x0100, 0x7F01, 0x807F, 0xFE80,
                                           0xFFFE, 0x34FF, 0x1234)):
            with self.subTest(offset=offset):
                self.assertEqual(extract_candidate(frames, 5, Candidate(offset, 16)),
                                 [(1, expected)])
        self.assertEqual(extract_candidate(frames, 6, Candidate(0, 16)), [])

    def test_candidate_configurations(self):
        expected = [Candidate(i, 8) for i in range(8)] + [Candidate(i, 16) for i in range(7)]
        self.assertEqual(byte_aligned_candidates(), expected)
        for offset, width in ((-1, 8), (8, 8), (7, 16), (0, 32), (0.5, 8)):
            with self.subTest(offset=offset, width=width), self.assertRaises(ValueError):
                Candidate(offset, width)

    def test_generated_log(self):
        frames = read_csv(ROOT / "datasets/synthetic/can_log.csv")
        self.assertEqual(len(frames), 36000)
        ids = [0x083, 0x1A4, 0x245, 0x316, 0x427, 0x6B2]
        self.assertEqual(unique_ids(frames), ids)
        self.assertEqual(frame_counts(frames), dict.fromkeys(ids, 6000))
        self.assertEqual(timestamp_bounds(frames), (0, 59.99))
        for hz in update_frequencies(frames).values():
            self.assertAlmostEqual(hz, 100)

    def test_cli_success_and_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "traffic.csv"
            path.write_text(HEADER + f"0,1,{PAYLOAD}\n0.01,1,{PAYLOAD}\n", encoding="utf-8")
            output = io.StringIO()
            with patch("sys.argv", ["canary.inspect", str(path)]), redirect_stdout(output):
                main()
            self.assertIn("Total frames: 2", output.getvalue())
            self.assertIn("Capture duration: 0.010000 s", output.getvalue())
            self.assertIn("0x001: 2 frames, estimated frequency 100.00 Hz", output.getvalue())
            path.write_text(HEADER + f"bad,1,{PAYLOAD}\n", encoding="utf-8")
            errors = io.StringIO()
            with patch("sys.argv", ["canary.inspect", str(path)]), redirect_stderr(errors):
                with self.assertRaises(SystemExit) as raised:
                    main()
            self.assertEqual(raised.exception.code, 2)
            self.assertIn("line 2: timestamp", errors.getvalue())

    def test_analysis_has_no_simulator_dependency(self):
        for path in (ROOT / "canary").rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotIn("ground_truth", source)
                self.assertNotIn("speed_reference", source)
                for node in ast.walk(ast.parse(source)):
                    if isinstance(node, ast.Import):
                        self.assertTrue(all(not alias.name.startswith("simulator") for alias in node.names))
                    elif isinstance(node, ast.ImportFrom):
                        self.assertFalse((node.module or "").startswith("simulator"))


if __name__ == "__main__":
    unittest.main()
