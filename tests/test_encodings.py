import csv
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from canary.agent import ToolDispatcher
from canary.discover import main
from canary.fitting import discover_and_fit, write_reconstruction
from canary.llm.base import ToolCall
from canary.observation import Candidate, Frame, byte_aligned_candidates, extract_candidate
from canary.reporting import write_report
from canary.tools import analyze_candidate, fit_candidate, list_candidate_fields, search_candidates


class EncodingTests(unittest.TestCase):
    def test_signed_eight_bit_boundaries(self):
        frames = [Frame(i, 1, bytes([raw]) + bytes(7)) for i, raw in enumerate((0, 0x7F, 0x80, 0xFF))]
        self.assertEqual([v for _, v in extract_candidate(frames, 1, Candidate(0, 8, signed=True))], [0, 127, -128, -1])
        self.assertEqual([v for _, v in extract_candidate(frames, 1, Candidate(0, 8))], [0, 127, 128, 255])

    def test_sixteen_bit_boundaries_both_endians(self):
        for endian, payloads in (("little", ["FFFF", "0080", "FF7F", "0000"]),
                                 ("big", ["FFFF", "8000", "7FFF", "0000"])):
            frames = [Frame(i, 1, bytes.fromhex(p) + bytes(6)) for i, p in enumerate(payloads)]
            with self.subTest(endian=endian):
                self.assertEqual([v for _, v in extract_candidate(frames, 1, Candidate(0, 16, endian, True))],
                                 [-1, -32768, 32767, 0])
                self.assertEqual([v for _, v in extract_candidate(frames, 1, Candidate(0, 16, endian))],
                                 [65535, 32768, 32767, 0])

    def test_endian_and_offset(self):
        frames = [Frame(0, 291, bytes.fromhex("AA BB 12 34 CC DD EE FF"))]
        self.assertEqual(extract_candidate(frames, 291, Candidate(2, 16)), [(0, 0x3412)])
        self.assertEqual(extract_candidate(frames, 291, Candidate(2, 16, "big")), [(0, 0x1234)])

    def test_enumeration_and_canonical_eight_bit(self):
        candidates = byte_aligned_candidates(291)
        self.assertEqual(len(candidates), 44)
        self.assertEqual(len(set(candidates)), 44)
        self.assertEqual(sum(c.width_bits == 8 for c in candidates), 16)
        self.assertEqual(sum(c.width_bits == 16 for c in candidates), 28)
        self.assertTrue(all(c.can_id == 291 and c.start_bit == c.byte_offset * 8 for c in candidates))
        self.assertEqual(Candidate(0, 8, "big", True), Candidate(0, 8, "little", True))

    def test_invalid_encodings(self):
        for args in ((0, 16, "middle", False), (0, 16, "big", 1), (7, 16, "big", True), (0, 12, "little", False)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                Candidate(*args)
        with self.assertRaises(ValueError):
            Candidate(0, 8, can_id=2048)
        with self.assertRaises(ValueError):
            extract_candidate([Frame(0, 1, bytes(8))], 1, Candidate(0, 8, can_id=2))

    def test_signed_big_endian_tools_and_serialization(self):
        values = [-32768, -300, -1, 0, 300, 32767]
        frames = [Frame(i, 291, v.to_bytes(2, "big", signed=True) + bytes(6)) for i, v in enumerate(values)]
        reference = [(i, v*0.037-12.5) for i, v in enumerate(values)]
        options = {"endian": "big", "signed": True}
        analysis = analyze_candidate(frames, 291, 0, 16, reference, include_fit=True, **options)
        fit = fit_candidate(frames, 291, 0, 16, reference, **options)
        self.assertEqual(analysis["raw_min"], -32768)
        self.assertEqual(analysis["raw_max"], 32767)
        self.assertEqual(fit["fit"], analysis["fit"])
        self.assertAlmostEqual(fit["fit"]["scale"], 0.037)
        self.assertAlmostEqual(fit["fit"]["offset"], -12.5)
        search = search_candidates(frames, reference)
        self.assertEqual((search["results"][0]["endian"], search["results"][0]["signed"]), ("big", True))
        fields = list_candidate_fields(frames, 291)
        json.dumps([analysis, fit, search, fields], allow_nan=False)
        dispatched = ToolDispatcher(frames, reference).dispatch(ToolCall("1", "analyze_candidate",
            {"can_id": 291, "byte_offset": 0, "width_bits": 16, "include_fit": True, **options}))
        self.assertEqual(dispatched["result"], analysis)

    def test_signed_big_endian_reconstruction_report_cli(self):
        values = [-300, -1, 0, 300]
        frames = [Frame(i, 291, v.to_bytes(2, "big", signed=True) + bytes(6)) for i, v in enumerate(values)]
        reference = [(i, v*2+5) for i, v in enumerate(values)]
        results = discover_and_fit(frames, reference, top_n=1)
        self.assertEqual((results[0].endian, results[0].signed), ("big", True))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_reconstruction(root / "out.csv", frames, reference, results[0])
            with (root / "out.csv").open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([int(r["raw"]) for r in rows], values)
            self.assertTrue(all(float(r["reference"]) == float(r["reconstructed"]) for r in rows))
            write_report(root / "report.html", frames, reference, results, "measurement")
            text = (root / "report.html").read_text(encoding="utf-8")
            self.assertIn("<dt>Endian</dt><dd>big</dd>", text)
            self.assertIn("<dt>Signed</dt><dd>yes</dd>", text)
            with (root / "can.csv").open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(("timestamp", "can_id", "data"))
                writer.writerows((f.timestamp, f.can_id, f.data.hex()) for f in frames)
            with (root / "ref.csv").open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(("timestamp", "value"))
                writer.writerows(reference)
            output = io.StringIO()
            with patch("sys.argv", ["canary.discover", str(root / "can.csv"), str(root / "ref.csv"),
                                      "--value-column", "value", "--fit", "--top", "1"]), redirect_stdout(output):
                main()
            self.assertIn("Endian:       big", output.getvalue())
            self.assertIn("Signed:       yes", output.getvalue())
