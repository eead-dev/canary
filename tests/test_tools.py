from contextlib import redirect_stdout
from dataclasses import asdict
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from canary.discovery import discover_signal
from canary.fitting import fit_linear
from canary.observation import Frame
from canary.tool_demo import main
from canary.tools import (analyze_candidate, fit_candidate, inspect_can_id, list_can_ids,
                          list_candidate_fields, search_candidates, summarize_capture)


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.frames = [Frame(i, 291, bytes([i]) + bytes(7)) for i in range(4)]
        self.reference = [(i, 2 * i + 5) for i in range(4)]

    def test_summary(self):
        self.assertEqual(summarize_capture(self.frames), {"total_frames": 4, "unique_can_id_count": 1,
                         "first_timestamp": 0, "last_timestamp": 3, "duration_seconds": 3})
        self.assertIsNone(summarize_capture([])["duration_seconds"])

    def test_id_listing(self):
        self.assertEqual(list_can_ids(self.frames), {"can_ids": [
            {"can_id": 291, "frame_count": 4, "update_frequency_hz": 1.0}]})
        self.assertEqual(list_can_ids([]), {"can_ids": []})

    def test_inspection(self):
        result = inspect_can_id(self.frames, 291)
        self.assertEqual(result["frame_count"], 4)
        self.assertEqual(result["update_frequency_hz"], 1)
        self.assertEqual(result["changing_byte_positions"], [0])
        self.assertEqual(result["byte_ranges"][0], {"byte_offset": 0, "raw_min": 0, "raw_max": 3})
        self.assertEqual(len(result["byte_ranges"]), 8)
        self.assertEqual(inspect_can_id(self.frames[:1], 291)["changing_byte_positions"], [])

    def test_candidate_listing(self):
        result = list_candidate_fields(self.frames, 291)
        self.assertEqual(len(result["candidates"]), 44)
        self.assertEqual([(r["byte_offset"], r["width_bits"]) for r in result["candidates"]],
                         [(i, w) for w in (8, 16) for i in range(9-w//8)
                          for _ in range(2 if w == 8 else 4)])
        self.assertTrue(all(r["start_bit"] == r["byte_offset"] * 8 for r in result["candidates"]))

    def test_analysis(self):
        result = analyze_candidate(self.frames, 291, 0, 8, self.reference, include_fit=True)
        self.assertAlmostEqual(result["correlation"], 1)
        self.assertEqual((result["aligned_samples"], result["raw_min"], result["raw_max"]), (4, 0, 3))
        self.assertEqual(result["fit"]["scale"], 2)
        self.assertNotIn("fit", analyze_candidate(self.frames, 291, 0, 8, self.reference))
        subset = analyze_candidate(self.frames, 291, 0, 8, self.reference[1:])
        self.assertEqual(subset["raw_min"], 1)

    def test_search_consistency(self):
        result = search_candidates(self.frames, self.reference, top_n=2)
        self.assertEqual(result["candidates_searched"], 44)
        expected = discover_signal(self.frames, self.reference)
        self.assertEqual(result["candidates_ranked"], len(expected))
        self.assertEqual(result["results"], [asdict(r) for r in expected[:2]])

    def test_fit_consistency(self):
        result = fit_candidate(self.frames, 291, 0, 8, self.reference)
        self.assertEqual(result["fit"], asdict(fit_linear([0, 1, 2, 3], [5, 7, 9, 11])))
        self.assertEqual(result["aligned_samples"], 4)

    def test_degenerate_results(self):
        result = analyze_candidate(self.frames, 291, 1, 8, self.reference, include_fit=True)
        self.assertIsNone(result["correlation"])
        self.assertIsNone(result["fit"])
        self.assertIsNone(fit_candidate(self.frames, 291, 0, 8, [])["fit"])
        result = analyze_candidate(self.frames, 291, 0, 8, [])
        self.assertEqual(result["aligned_samples"], 0)
        self.assertIsNone(result["raw_min"])

    def test_invalid_inputs(self):
        for can_id in (-1, 2048, "291", True, 1):
            for tool in (inspect_can_id, list_candidate_fields):
                with self.subTest(tool=tool.__name__, can_id=can_id), self.assertRaises(ValueError):
                    tool(self.frames, can_id)
        for offset, width in ((-1, 8), (7, 16), (8, 8), (0, 32), (0.5, 8)):
            for tool in (analyze_candidate, fit_candidate):
                with self.subTest(offset=offset, width=width), self.assertRaises(ValueError):
                    tool(self.frames, 291, offset, width, self.reference)
        for reference in ([1], [(0, "bad")], [(0, float("nan"))], [(1, 1), (0, 2)]):
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                search_candidates(self.frames, reference)
        for options in ({"top_n": 0}, {"top_n": True}, {"tolerance": -1}, {"min_samples": 2}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                search_candidates(self.frames, self.reference, **options)
        with self.assertRaises(ValueError):
            summarize_capture([{}])

    def test_json_serialization(self):
        outputs = [summarize_capture(self.frames), list_can_ids(self.frames), inspect_can_id(self.frames, 291),
                   list_candidate_fields(self.frames, 291), search_candidates(self.frames, self.reference),
                   analyze_candidate(self.frames, 291, 0, 8, self.reference, include_fit=True),
                   fit_candidate(self.frames, 291, 0, 8, self.reference)]
        self.assertEqual(json.loads(json.dumps(outputs, allow_nan=False)), outputs)

    def test_demo(self):
        with tempfile.TemporaryDirectory() as directory:
            can, ref = Path(directory) / "can.csv", Path(directory) / "ref.csv"
            can.write_text("timestamp,can_id,data\n" + "".join(
                f"{i},291,{i:02X} 00 00 00 00 00 00 00\n" for i in range(4)), encoding="utf-8")
            ref.write_text("timestamp,value\n0,5\n1,7\n2,9\n3,11\n", encoding="utf-8")
            output = io.StringIO()
            with patch("sys.argv", ["canary.tool_demo", str(can), str(ref), "--value-column", "value"]), redirect_stdout(output):
                main()
            parsed = json.loads(output.getvalue())
            self.assertEqual(set(parsed), {"summarize_capture", "list_can_ids", "inspect_can_id",
                                          "list_candidate_fields", "analyze_candidate", "search_candidates", "fit_candidate"})


if __name__ == "__main__":
    unittest.main()
