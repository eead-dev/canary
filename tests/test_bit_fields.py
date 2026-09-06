import csv
from contextlib import redirect_stdout
from dataclasses import asdict
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from canary.agent import ToolDispatcher, checked_conclusion
from canary.alignment import AlignmentConfig, align_series
from canary.discover import main
from canary.discovery import discover_signal, pearson
from canary.fitting import discover_and_fit, write_reconstruction
from canary.llm.base import ToolCall
from canary.observation import Candidate, CandidateSpec, Frame, byte_aligned_candidates, candidate_fields, extract_candidate
from canary.reporting import write_report
from canary.tools import analyze_candidate, fit_candidate, list_candidate_fields


class BitFieldTests(unittest.TestCase):
    def test_cross_byte_little_endian(self):
        frame = Frame(0, 1, bytes.fromhex("80 57 01 00 00 00 00 00"))
        self.assertEqual(extract_candidate([frame], 1, CandidateSpec(5, 12)), [(0, 0xABC)])

    def test_cross_byte_big_endian_msb0(self):
        frame = Frame(0, 1, bytes.fromhex("05 5E 00 00 00 00 00 00"))
        self.assertEqual(extract_candidate([frame], 1, CandidateSpec(5, 12, "big")), [(0, 0xABC)])

    def test_twelve_bit_unsigned_and_signed_boundaries(self):
        for endian in ("little", "big"):
            shift = 19 if endian == "little" else 64-19-12
            frames = [Frame(i, 1, (value << shift).to_bytes(8, endian))
                      for i, value in enumerate((0, 0x7FF, 0x800, 0xFFF))]
            with self.subTest(endian=endian):
                self.assertEqual([v for _, v in extract_candidate(frames, 1, CandidateSpec(19, 12, endian))],
                                 [0, 2047, 2048, 4095])
                self.assertEqual([v for _, v in extract_candidate(frames, 1, CandidateSpec(19, 12, endian, True))],
                                 [0, 2047, -2048, -1])

    def test_legacy_byte_aligned_decoding_exactly_preserved(self):
        payloads = [bytes.fromhex(p) for p in ("007F80FFFF0080AA", "123456789ABCDEF0", "FFFFFFFFFFFFFFFF")]
        frames = [Frame(i, 1, payload) for i, payload in enumerate(payloads)]
        for candidate in byte_aligned_candidates(1):
            start, width = candidate.byte_offset, candidate.width_bits // 8
            expected = [(i, int.from_bytes(p[start:start+width], candidate.endian, signed=candidate.signed))
                        for i, p in enumerate(payloads)]
            self.assertEqual(extract_candidate(frames, 1, candidate), expected)

    def test_enumeration_uniqueness_and_bit_oracle(self):
        candidates = candidate_fields(1)
        self.assertEqual(len(candidates), 620)
        self.assertEqual(len(set(candidates)), 620)
        self.assertEqual({w: sum(c.width_bits == w for c in candidates) for w in (8, 12, 16)},
                         {8: 212, 12: 212, 16: 196})
        # One-hot payloads identify the exact source bits and their signed weights.
        frames = [Frame(i, 1, (1 << i).to_bytes(8, "little")) for i in range(64)]
        signatures = set()
        for candidate in candidates:
            values = tuple(v for _, v in extract_candidate(frames, 1, candidate))
            self.assertNotIn(values, signatures)
            signatures.add(values)
            for frame, actual in zip(frames, values):
                bits = []
                for bit in range(candidate.start_bit, candidate.start_bit + candidate.width_bits):
                    byte, within = divmod(bit, 8)
                    bits.append((frame.data[byte] >> (within if candidate.endian == "little" else 7-within)) & 1)
                if candidate.endian == "big":
                    bits.reverse()
                expected = sum(bit << i for i, bit in enumerate(bits))
                if candidate.signed and bits[-1]:
                    expected -= 1 << candidate.width_bits
                self.assertEqual(actual, expected)

    def test_invalid_and_conflicting_locators(self):
        for start, width in ((-1, 12), (53, 12), (49, 16), (57, 8), (0, 10), (True, 12)):
            with self.subTest(start=start, width=width), self.assertRaises(ValueError):
                CandidateSpec(start, width)
        with self.assertRaises(ValueError):
            Candidate(2, 12, start_bit=19)
        self.assertIsNone(CandidateSpec(19, 12).byte_offset)
        self.assertEqual(CandidateSpec(16, 12).byte_offset, 2)

    def test_cached_search_matches_independent_alignment(self):
        frames = [Frame(t, 1, bytes.fromhex(p)) for t, p in (
            (1.1, "80000123456789AB"), (0.1, "123456789ABCDEFF"), (1.1, "F0123456789ABCDE"),
            (2.1, "0011223344556677"), (3.1, "ABCDEFFF0055AABB"))]
        reference = [(0, 1), (1, 4), (2, 2), (3, 8), (4, 3)]
        actual = discover_signal(frames, reference, alignment="nearest", tolerance=0.2)
        expected = {}
        for c in candidate_fields(1):
            aligned = align_series(extract_candidate(frames, 1, c), reference, AlignmentConfig("nearest", 0.2))
            r = pearson([x for _, x, _ in aligned.rows], [y for _, _, y in aligned.rows])
            if r is not None:
                expected[(c.start_bit, c.width_bits, c.endian, c.signed)] = (r, aligned.diagnostics)
        self.assertEqual(len(actual), len(expected))
        for result in actual:
            self.assertEqual((result.correlation, result.alignment_diagnostics),
                             expected[(result.start_bit, result.width_bits, result.endian, result.signed)])

    def test_tools_cli_and_report_non_aligned(self):
        # Exercise signed cross-byte BE reconstruction, without relying on discovery winning a tie.
        raw_values = [-2048, -1000, -1, 0, 123, 2047]
        frames = [Frame(i, 1, ((v & 0xFFF) << (64-5-12)).to_bytes(8, "big")) for i, v in enumerate(raw_values)]
        reference = [(i, v*0.25+7) for i, v in enumerate(raw_values)]
        args = {"start_bit": 5, "width_bits": 12, "endian": "big", "signed": True}
        analysis = analyze_candidate(frames, 1, reference=reference, include_fit=True, **args)
        fit = fit_candidate(frames, 1, reference=reference, **args)
        self.assertNotIn("byte_offset", analysis)
        self.assertEqual(analysis["raw_min"], -2048)
        self.assertEqual(fit["fit"]["scale"], 0.25)
        self.assertAlmostEqual(fit["fit"]["offset"], 7)
        json.dumps([analysis, fit, list_candidate_fields(frames, 1)], allow_nan=False)
        self.assertTrue(ToolDispatcher(frames, reference).dispatch(ToolCall("1", "analyze_candidate",
                            {"can_id": 1, **args}))["ok"])
        from canary.fitting import fit_ranked
        ranked = discover_signal(frames, reference)
        selected = next(r for r in ranked if (r.start_bit, r.width_bits, r.endian, r.signed) == (5, 12, "big", True))
        conclusion = {"reference_name": "measurement", "selected_candidate": {"can_id": 1, **args},
                      "correlation": analysis["correlation"], **analysis["fit"],
                      "confidence": "medium", "rationale": "Collected fit evidence."}
        group = analysis["equivalence"]
        equivalents = [c for c in [group["representative"], *group["equivalent_candidates"]]
                       if (c["start_bit"], c["width_bits"], c["endian"], c["signed"]) != (5, 12, "big", True)]
        conclusion.update(signal_confidence="high", layout_confidence="low" if equivalents else "high",
                          layout_ambiguous=bool(equivalents), equivalent_layouts=equivalents,
                          alternative_candidates=[])
        conclusion.update(affine_equivalent_layouts=[e['candidate'] for e in analysis['affine_equivalents']],
                          ambiguity_reason=analysis['ambiguity_reason'],
                          layout_ambiguous=analysis['layout_ambiguous'],
                          layout_confidence='low' if analysis['layout_ambiguous'] else 'high')
        trace = [{"name": "search_candidates", "output": {"ok": True, "result": {"results": [asdict(selected)]}}},
                 {"name": "analyze_candidate", "output": {"ok": True, "result": analysis}}]
        self.assertEqual(checked_conclusion(conclusion, "measurement", trace).selected_candidate["start_bit"], 5)
        fitted = fit_ranked(frames, reference, [selected])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_reconstruction(root / "out.csv", frames, reference, fitted[0])
            with (root / "out.csv").open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([int(r["raw"]) for r in rows], raw_values)
            write_report(root / "report.html", frames, reference, fitted, "measurement")
            text = (root / "report.html").read_text(encoding="utf-8")
            self.assertIn("<dt>Start bit</dt><dd>5</dd>", text)
            self.assertNotIn("<dt>Byte offset</dt>", text)
            with patch("canary.discover.read_csv", return_value=frames), patch("canary.discover.read_reference", return_value=reference), \
                 patch("canary.discover.discover_signal", return_value=[selected]), \
                 patch("sys.argv", ["canary.discover", "can.csv", "ref.csv", "--value-column", "value", "--fit"]), \
                 redirect_stdout(io.StringIO()) as output:
                main()
            self.assertIn("Start bit:    5", output.getvalue())
            self.assertNotIn("Byte offset:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
