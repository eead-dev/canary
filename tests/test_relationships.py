from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest

from canary.analysis import AnalysisRun
from canary.agent import checked_conclusion
from canary.discovery import discover_signal, pearson
from canary.fitting import fit_ranked
from canary.observation import CandidateSpec, Frame
from canary.relationships import compare_raw_series, RESIDUAL_TOLERANCE
from canary.reporting import write_report
from canary.tools import analyze_candidate, search_candidates


class RelationshipTests(unittest.TestCase):
    def test_real_relationship(self):
        defined = [8000, 8123, 8765, 9311, 10000, 11111, 12000]
        discovered = [4*v-65536 for v in defined]
        evidence = compare_raw_series(defined, discovered)
        self.assertEqual(evidence.relationship_type, 'affine')
        self.assertEqual(evidence.scale_between_raw, 4)
        self.assertEqual(evidence.offset_between_raw, -65536)
        self.assertLessEqual(evidence.max_abs_residual, RESIDUAL_TOLERANCE)
        self.assertEqual(evidence.sample_count, len(defined))

    def test_exact(self):
        result = compare_raw_series([1, 3, 8], [1, 3, 8])
        self.assertEqual((result.relationship_type, result.scale_between_raw, result.offset_between_raw),
                         ('exact', 1, 0))

    def test_sign_flip_and_offset(self):
        for scale, offset in ((-4, 0), (1, 700), (-0.5, 42)):
            x = [1, 3, 8, 20, 100]
            result = compare_raw_series(x, [scale*v+offset for v in x])
            self.assertEqual(result.relationship_type, 'affine')
            self.assertAlmostEqual(result.scale_between_raw, scale)
            self.assertAlmostEqual(result.offset_between_raw, offset)

    def test_highly_correlated_not_affine(self):
        x = list(range(1000))
        y = [4*v + (v % 2) for v in x]
        self.assertGreater(pearson(x, y), .99999)
        self.assertEqual(compare_raw_series(x, y).relationship_type, 'distinct')

    def test_noise_and_single_outlier_rejected(self):
        x = list(range(1000))
        for y in ([4*v + (1e-5 if v % 2 else 0) for v in x], [4*v for v in x[:-1]] + [3996.001]):
            result = compare_raw_series(x, y)
            self.assertEqual(result.relationship_type, 'distinct')
            self.assertGreater(result.max_abs_residual, RESIDUAL_TOLERANCE)

    def test_roundoff_only(self):
        x = [1, 2, 3, 4]
        self.assertEqual(compare_raw_series(x, [1, 2+1e-10, 3, 4]).relationship_type, 'affine')

    def test_degenerate_series(self):
        for x, y in (([], []), ([1, 2], [3, 4]), ([1]*3, [1]*3), ([1, 2, 3], [4]*3)):
            result = compare_raw_series(x, y)
            self.assertEqual(result.relationship_type, 'distinct')
            self.assertIsNone(result.scale_between_raw)
            json.dumps(asdict(result), allow_nan=False)

    def test_invalid_inputs(self):
        for x, y in (([1], [1, 2]), ([1, 2, float('nan')], [1, 2, 3]), ([1, 2, 3], [1, 2, float('inf')])):
            with self.assertRaises(ValueError):
                compare_raw_series(x, y)

    def fixture(self):
        values = [9000, 9123, 9765, 10311, 11000, 12111, 13000]
        frames = [Frame(i, 170, (v << 16).to_bytes(8, 'big')) for i, v in enumerate(values)]
        return frames, [(i, .01*v-67) for i, v in enumerate(values)]

    def test_grouping_cache_ranking_and_tools(self):
        frames, reference = self.fixture()
        run = AnalysisRun(frames, reference)
        before = discover_signal(frames, reference, run=run)
        a = CandidateSpec(32, 16, 'big', False, 170)
        b = CandidateSpec(34, 16, 'big', True, 170)
        evidence = run.ambiguity(a)
        relationship = next(e for e in evidence['affine_equivalents'] if e['candidate'] == asdict(b))
        self.assertEqual(relationship['scale_between_raw'], 4)
        self.assertEqual(relationship['offset_between_raw'], -65536)
        self.assertIs(run.raw_relationship(a, b), run.raw_relationship(a, b))
        self.assertNotEqual(run.series_key(a), run.series_key(b))
        self.assertIsNot(run.aligned(a), run.aligned(b))
        self.assertEqual(before, discover_signal(frames, reference, run=run))
        result = analyze_candidate(frames, 170, start_bit=32, width_bits=16, endian='big',
                                   reference=reference, include_fit=True, run=run)
        self.assertEqual(result['affine_equivalents'], evidence['affine_equivalents'])
        search = search_candidates(frames, reference, run=run)
        for h in search['hypotheses']:
            for key in ('exact_raw_equivalents', 'affine_equivalents', 'distinct_alternatives'):
                self.assertIn(key, h)
        json.dumps([result, search], allow_nan=False)

    def test_axes_must_match(self):
        frames, reference = self.fixture()
        frames += [Frame(f.timestamp+.01, 171, f.data) for f in frames]
        run = AnalysisRun(frames, reference, alignment='nearest', tolerance=.02)
        a, b = CandidateSpec(32, 16, 'big', False, 170), CandidateSpec(32, 16, 'big', False, 171)
        with self.assertRaisesRegex(ValueError, 'axes'):
            run.raw_relationship(a, b)
        self.assertEqual(run.ambiguity(a, [b])['distinct_alternatives'][0]['relationship_type'], 'uncompared')

    def test_html_affine_evidence(self):
        frames, reference = self.fixture()
        run = AnalysisRun(frames, reference)
        ranked = discover_signal(frames, reference, run=run)
        fits = fit_ranked(frames, reference, ranked[:5], run=run)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'report.html'
            write_report(path, frames, reference, fits, '<reference>', run=run)
            text = path.read_text(encoding='utf-8')
        self.assertIn('Affine-equivalent reconstructions', text)
        self.assertIn('cannot distinguish their physical reconstruction', text)
        self.assertIn('other_raw =', text)
        self.assertIn('&lt;reference&gt;', text)

    def test_agent_cannot_claim_unique_affine_layout(self):
        frames, reference = self.fixture()
        search = search_candidates(frames, reference, top_n=1)
        selected = search['hypotheses'][0]['representative']
        analysis = analyze_candidate(frames, reference=reference, include_fit=True, **selected)
        data = {'reference_name': 'measurement', 'selected_candidate': selected,
                'correlation': analysis['correlation'], **analysis['fit'], 'confidence': 'high',
                'signal_confidence': 'high', 'layout_confidence': 'low', 'layout_ambiguous': True,
                'equivalent_layouts': analysis['exact_raw_equivalents'],
                'affine_equivalent_layouts': [e['candidate'] for e in analysis['affine_equivalents']],
                'ambiguity_reason': 'affine_equivalent_layouts', 'alternative_candidates': [], 'rationale': 'Ambiguous.'}
        trace = [{'name': name, 'output': {'ok': True, 'result': result}} for name, result in
                 (('search_candidates', search), ('analyze_candidate', analysis))]
        self.assertTrue(checked_conclusion(data, 'measurement', trace).layout_ambiguous)
        for change in ({'layout_confidence': 'high'}, {'affine_equivalent_layouts': []},
                       {'ambiguity_reason': 'none'}, {'layout_ambiguous': False}):
            with self.assertRaises(ValueError):
                checked_conclusion({**data, **change}, 'measurement', trace)
