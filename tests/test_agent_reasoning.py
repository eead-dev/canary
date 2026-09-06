"""Offline reasoning fixtures; no provider SDK or live requests."""

from copy import deepcopy
import csv
from dataclasses import asdict
import json
from pathlib import Path
import random
import tempfile
import unittest

from canary.agent import SYSTEM, checked_conclusion, run_agent, validate, CONCLUSION_SCHEMA
from canary.llm.fake import FakeProvider


def make_case(directory, case):
    rng = random.Random(130)
    start, width, signed = (19, 12, True) if case in ('unique', 'distractor', 'noisy') else (16, 16, False)
    limit = 32767 if case == 'signedness' else 4095
    values = ([rng.randint(-2048, 2047) for _ in range(100)] if signed
              else [rng.randint(0, limit) for _ in range(100)])
    frames, reference = [], []
    mask = ((1 << width)-1) << start
    for i, value in enumerate(values):
        payload = (rng.getrandbits(64) & ~mask) | ((value & ((1 << width)-1)) << start)
        frames.append((i/100, 420, payload.to_bytes(8, 'little').hex()))
        reference.append((i/100, value*0.25+7 + (rng.gauss(0, 90) if case == 'noisy' else 0)))
        if case == 'distractor':
            distractor = max(-2048, min(2047, value + rng.choice((-4, -2, 2, 4))))
            data = (rng.getrandbits(64) & ~mask) | ((distractor & 0xFFF) << start)
            frames.append((i/100, 421, data.to_bytes(8, 'little').hex()))
    can, ref = Path(directory)/'can.csv', Path(directory)/'reference.csv'
    for path, header, rows in ((can, ('timestamp', 'can_id', 'data'), frames),
                               (ref, ('timestamp', 'measurement'), reference)):
        with path.open('w', newline='', encoding='utf-8') as stream:
            writer = csv.writer(stream)
            writer.writerow(header)
            writer.writerows(rows)
    return can, ref


class AgentReasoningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = {}
        for case in ('unique', 'width', 'distractor', 'noisy', 'signedness'):
            with tempfile.TemporaryDirectory() as directory:
                can, ref = make_case(directory, case)
                cls.runs[case] = run_agent(can, ref, 'measurement', FakeProvider())

    def conclusion(self, case):
        run = self.runs[case]
        self.assertEqual(run.status, 'complete', asdict(run))
        return asdict(run.conclusion)

    def test_unique_layout_conclusion(self):
        data = self.conclusion('unique')
        self.assertEqual((data['signal_confidence'], data['layout_confidence'], data['layout_ambiguous']),
                         ('high', 'high', False))
        self.assertEqual(data['equivalent_layouts'], [])
        self.assertEqual(data['selected_candidate'], {'can_id': 420, 'start_bit': 19,
                         'width_bits': 12, 'endian': 'little', 'signed': True})

    def test_width_ambiguity_propagated(self):
        data = self.conclusion('width')
        self.assertEqual(data['signal_confidence'], 'high')
        self.assertIn(data['layout_confidence'], ('low', 'medium'))
        self.assertTrue(data['layout_ambiguous'])
        self.assertEqual(data['selected_candidate']['width_bits'], 12)
        self.assertIn({'can_id': 420, 'start_bit': 16, 'width_bits': 16, 'endian': 'little', 'signed': False},
                      data['equivalent_layouts'])
        self.assertIn('cannot distinguish', data['rationale'])

    def test_distractor_compared_with_fit_evidence(self):
        data = self.conclusion('distractor')
        self.assertEqual(data['selected_candidate']['can_id'], 420)
        other = next(a for a in data['alternative_candidates'] if a['candidate']['can_id'] == 421)
        self.assertGreater(other['rmse'], data['rmse'])
        self.assertLess(other['r_squared'], data['r_squared'])
        inspected = [e['arguments']['can_id'] for e in self.runs['distractor'].trace if e['name'] == 'analyze_candidate']
        self.assertIn(420, inspected)
        self.assertIn(421, inspected)

    def test_noisy_reference_reduces_confidence(self):
        data = self.conclusion('noisy')
        self.assertIn(data['signal_confidence'], ('low', 'medium'))
        self.assertGreater(data['rmse'], self.conclusion('unique')['rmse'])
        self.assertLess(data['r_squared'], self.conclusion('unique')['r_squared'])

    def test_signed_unsigned_ambiguity(self):
        data = self.conclusion('signedness')
        self.assertTrue(data['layout_ambiguous'])
        self.assertNotEqual(data['layout_confidence'], 'high')
        self.assertTrue(any(c['signed'] != data['selected_candidate']['signed'] and c['width_bits'] == 16
                            for c in data['equivalent_layouts']))

    def test_ranked_distinct_hypotheses_and_json(self):
        for case, run in self.runs.items():
            data = self.conclusion(case)
            validate(data, CONCLUSION_SCHEMA)
            self.assertEqual(json.loads(json.dumps(asdict(run), allow_nan=False)), asdict(run))
            search = next(e['output']['result'] for e in run.trace if e['name'] == 'search_candidates')
            self.assertEqual([r['rank'] for r in search['results']], list(range(1, len(search['results'])+1)))
            representatives = [json.dumps(h['representative'], sort_keys=True) for h in search['hypotheses']]
            self.assertEqual(len(representatives), len(set(representatives)))
            for hypothesis in search['hypotheses']:
                self.assertEqual(hypothesis['equivalence_count'], len(hypothesis['equivalent_candidates'])+1)
                self.assertIn('identical decoded time series', hypothesis['evidence'])

    def test_unsupported_scale_wording_absent(self):
        self.assertIn('Do not describe a scale as standard or canonical', SYSTEM)
        for case in self.runs:
            data = self.conclusion(case)
            reasoning = ' '.join([data['rationale'], *[a['reason'] for a in data['alternative_candidates']]]).lower()
            self.assertNotIn('standard', reasoning)
            self.assertNotIn('canonical', reasoning)

    def test_malformed_or_fabricated_ambiguity_rejected(self):
        run = self.runs['width']
        original = self.conclusion('width')
        mutations = [dict(layout_ambiguous=False), dict(layout_confidence='high'), dict(equivalent_layouts=[]),
                     dict(signal_confidence='certain'), dict(layout_ambiguous=1), dict(alternative_candidates='none'),
                     dict(equivalent_layouts=original['equivalent_layouts']*2), dict(alternative_candidates=[])]
        for change in mutations:
            with self.subTest(change=change), self.assertRaises(ValueError):
                checked_conclusion({**original, **change}, 'measurement', run.trace)
        missing = deepcopy(original)
        del missing['signal_confidence']
        with self.assertRaises(ValueError):
            checked_conclusion(missing, 'measurement', run.trace)
        fabricated = deepcopy(original)
        fabricated['alternative_candidates'][0]['rmse'] += 10
        with self.assertRaisesRegex(ValueError, 'metrics'):
            checked_conclusion(fabricated, 'measurement', run.trace)
        fake_layout = deepcopy(original)
        fake_layout['equivalent_layouts'][0]['can_id'] = 2047
        with self.assertRaises(ValueError):
            checked_conclusion(fake_layout, 'measurement', run.trace)

    def test_malformed_conclusion_receives_correction(self):
        class CorrectingFake(FakeProvider):
            def __init__(self):
                self.malformed_sent = False
                self.saw_correction = False

            def respond(self, system, messages, tools, schema):
                self.saw_correction |= any(m.role == 'user' and 'error' in m.content for m in messages)
                response = super().respond(system, messages, tools, schema)
                if response.conclusion is not None and not self.malformed_sent:
                    response.conclusion['layout_ambiguous'] = not response.conclusion['layout_ambiguous']
                    self.malformed_sent = True
                return response
        with tempfile.TemporaryDirectory() as directory:
            can, ref = make_case(directory, 'width')
            provider = CorrectingFake()
            result = run_agent(can, ref, 'measurement', provider)
        self.assertEqual(result.status, 'complete')
        self.assertEqual(result.turns, 4)
        self.assertTrue(provider.saw_correction)
