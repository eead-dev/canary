import json
import unittest

from canary.agent import ToolDispatcher
from canary.llm.base import ToolCall
from canary.observation import CandidateSpec, Frame, candidate_fields, extract_candidate


class FifteenBitTests(unittest.TestCase):
    def test_boundaries_at_every_start_and_endian(self):
        raw = [0, 0x3FFF, 0x4000, 0x7FFF]
        for endian in ('little', 'big'):
            for start in range(50):
                shift = start if endian == 'little' else 64-start-15
                mask = 0x7FFF << shift
                frames = [Frame(i, 123, (((1 << 64)-1 & ~mask) | (v << shift)).to_bytes(8, endian))
                          for i, v in enumerate(raw)]
                for signed, expected in ((False, raw), (True, [0, 16383, -16384, -1])):
                    with self.subTest(endian=endian, start=start, signed=signed):
                        c = CandidateSpec(start, 15, endian, signed, 123)
                        self.assertEqual([v for _, v in extract_candidate(frames, 123, c)], expected)

    def test_only_fifteen_added_and_counts(self):
        candidates = candidate_fields(123)
        self.assertEqual(len(candidates), 820)
        self.assertEqual(sum(c.width_bits != 15 for c in candidates), 620)
        self.assertEqual(sum(c.width_bits == 15 for c in candidates), 200)
        self.assertEqual(len(candidates)*6, 4920)
        self.assertEqual(len(candidates)*90, 73800)
        for width in (9, 14, 17):
            with self.assertRaises(ValueError):
                CandidateSpec(0, width)
        with self.assertRaises(ValueError):
            CandidateSpec(50, 15)

    def test_tool_schema_and_json(self):
        frames = [Frame(i, 123, (v << 19).to_bytes(8, 'little')) for i, v in enumerate((0, 0x3FFF, 0x4000, 0x7FFF))]
        reference = list(enumerate([0, 16383, -16384, -1]))
        result = ToolDispatcher(frames, reference).dispatch(ToolCall('15', 'analyze_candidate',
            {'can_id': 123, 'start_bit': 19, 'width_bits': 15, 'signed': True, 'include_fit': True}))
        self.assertTrue(result['ok'])
        self.assertEqual(result['result']['fit']['scale'], 1)
        json.dumps(result, allow_nan=False)
