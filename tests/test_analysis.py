from dataclasses import asdict
import json
import math
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from canary.analysis import AnalysisRun
from canary.discovery import discover_signal
from canary.fitting import fit_ranked, write_reconstruction
from canary.observation import CandidateSpec, Frame, candidate_fields, decode_words, extract_candidate
from canary.reporting import write_report
from canary.tools import analyze_candidate, fit_candidate, inspect_can_id, search_candidates


def original_pearson(xs, ys):
    # Ticket #11 arithmetic, independent of the prepared-reference implementation.
    if len(xs) < 3:
        return None
    centered = []
    for values in (xs, ys):
        magnitude = max(abs(v) for v in values)
        normalized = [v / magnitude for v in values] if magnitude else [0.0] * len(values)
        mean = math.fsum(normalized) / len(values)
        centered.append([v - mean for v in normalized])
    dx, dy = centered
    xx, yy = math.fsum(v*v for v in dx), math.fsum(v*v for v in dy)
    if xx == 0 or yy == 0:
        return None
    return max(-1.0, min(1.0, math.fsum(x*y for x, y in zip(dx, dy)) / math.sqrt(xx) / math.sqrt(yy)))


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.values = [0, 123, 2400, 4095, 3200, 77]
        self.frames = [Frame(i, 420, (v << 16).to_bytes(8, 'little')) for i, v in enumerate(self.values)]
        self.reference = [(i, v*0.037-12.5) for i, v in enumerate(self.values)]
        self.run = AnalysisRun(self.frames, self.reference)
        self.short = CandidateSpec(16, 12, can_id=420)
        self.long = CandidateSpec(16, 16, can_id=420)

    def test_cache_reuse_across_consumers(self):
        with patch('canary.analysis.decode_words', wraps=decode_words) as decoder:
            ranked = discover_signal(self.frames, self.reference, run=self.run)
            calls = decoder.call_count
            chosen = next(r for r in ranked if r.start_bit == 16 and r.width_bits == 12 and not r.signed and r.endian == 'little')
            fitted = fit_ranked(self.frames, self.reference, [chosen], run=self.run)
            selection = dict(start_bit=16, width_bits=12, run=self.run)
            analysis = analyze_candidate(self.frames, 420, reference=self.reference, include_fit=True, **selection)
            fit = fit_candidate(self.frames, 420, reference=self.reference, **selection)
            self.assertEqual(analysis['fit'], fit['fit'])
            inspect_can_id(self.frames, 420, run=self.run)
            with tempfile.TemporaryDirectory() as directory:
                write_report(Path(directory)/'report.html', self.frames, self.reference, fitted, '<measurement>', run=self.run)
                write_reconstruction(Path(directory)/'raw.csv', self.frames, self.reference, fitted[0], run=self.run)
                html = (Path(directory)/'report.html').read_text(encoding='utf-8')
                self.assertIn('Equivalent layouts', html)
                self.assertIn('Layout is ambiguous', html)
                self.assertIn('&lt;measurement&gt;', html)
                self.assertIn('Search performance', html)
            self.assertEqual(decoder.call_count, calls)
            self.assertIs(self.run.decoded(self.short), self.run.decoded(self.long))
            self.assertIs(self.run.fit(self.short), self.run.fit(self.long))
            self.assertEqual(discover_signal(self.frames, self.reference, run=self.run), ranked)

    def test_exact_equivalence_retains_every_layout(self):
        ranked = discover_signal(self.frames, self.reference, run=self.run)
        group = self.run.equivalence(self.short)
        self.assertIn(self.long, [group.representative, *group.equivalent_candidates])
        self.assertEqual(group.equivalence_count, 1+len(group.equivalent_candidates))
        self.assertEqual(group.representative, self.short)
        identities = {(r.can_id, r.start_bit, r.width_bits, r.endian, r.signed) for r in ranked}
        self.assertIn((420, 16, 16, 'little', False), identities)
        self.assertEqual(self.run.statistics()['candidates_enumerated'], 820)
        self.assertEqual(sum(g.equivalence_count for g in {id(v): v for v in self.run._classes.values()}.values()), 820)

    def test_equal_correlation_is_not_equivalence(self):
        # A shifted field can have exactly proportional values, but distinct raws.
        candidate = CandidateSpec(15, 16, can_id=420)
        self.assertEqual(self.run.correlation(candidate), self.run.correlation(self.short))
        self.assertNotEqual(self.run.equivalence(candidate), self.run.equivalence(self.short))

    def test_constants_skip_pearson_work(self):
        frames = [Frame(i, 1, bytes(8)) for i in range(4)]
        run = AnalysisRun(frames, list(enumerate([1, 2, 4, 8])))
        with patch('canary.discovery._prepare', side_effect=AssertionError('constant needs no Pearson')):
            self.assertEqual(discover_signal(frames, list(enumerate([1, 2, 4, 8])), run=run), [])
        stats = run.statistics()
        self.assertEqual(stats['constant_candidates_skipped'], 820)
        self.assertEqual(stats['unique_decoded_series'], 1)
        self.assertEqual(stats['equivalent_candidates_grouped'], 819)

    def test_original_correlation_and_coverage(self):
        rng = random.Random(74)
        frames = [Frame(i, 1, rng.randbytes(8)) for i in range(25)]
        reference = [(i, rng.uniform(-10, 10)) for i in range(25)]
        expected = {}
        for c in candidate_fields(1):
            score = original_pearson([v for _, v in extract_candidate(frames, 1, c)], [v for _, v in reference])
            if score is not None:
                expected[(c.start_bit, c.width_bits, c.endian, c.signed)] = score
        results = discover_signal(frames, reference)
        self.assertEqual(len(results), len(expected))
        for r in results:
            self.assertEqual(r.correlation, expected[(r.start_bit, r.width_bits, r.endian, r.signed)])

    def test_alignment_scope_and_unmatched_values(self):
        # Reference excludes the first frame where the two widths differ.
        frames = [Frame(0, 420, (60000 << 16).to_bytes(8, 'little')), *self.frames[1:]]
        run = AnalysisRun(frames, self.reference[1:])
        self.assertNotEqual(run.decoded(self.short), run.decoded(self.long))
        self.assertEqual(run.aligned(self.short), run.aligned(self.long))
        self.assertEqual(run.equivalence(self.short), run.equivalence(self.long))
        self.assertEqual(len(run.rows(self.short)), 5)

    def test_timestamp_axes_and_deterministic_representative(self):
        frames = self.frames + [Frame(f.timestamp, 421, f.data) for f in self.frames]
        run = AnalysisRun(frames, self.reference)
        group = run.equivalence(self.short)
        other = CandidateSpec(16, 12, can_id=421)
        self.assertEqual(group, run.equivalence(other))
        reverse = AnalysisRun(list(reversed(frames)), self.reference)
        self.assertEqual(group, reverse.equivalence(other))
        shifted = self.frames + [Frame(f.timestamp+0.1, 421, f.data) for f in self.frames]
        ref = sorted(self.reference + [(t+0.1, y) for t, y in self.reference])
        different = AnalysisRun(shifted, ref)
        self.assertNotEqual(different.equivalence(self.short), different.equivalence(other))

    def test_snapshot_and_configuration_validation(self):
        before = list(self.run.decoded(self.short).values)
        self.frames[0] = Frame(0, 420, bytes(8))
        self.reference[0] = (0, 88)
        self.assertEqual(list(self.run.decoded(self.short).values), before)
        with self.assertRaisesRegex(ValueError, 'does not match'):
            discover_signal(self.frames, self.reference, run=self.run)
        with self.assertRaisesRegex(ValueError, 'does not match'):
            discover_signal(list(self.run.frames), list(self.run.reference), run=self.run, tolerance=0.1)
        with self.assertRaises(TypeError):
            self.run.decoded(self.short).values[0] = 8

    def test_tool_json_and_statistics(self):
        output = search_candidates(self.frames, self.reference, run=self.run)
        self.assertEqual(json.loads(json.dumps(output, allow_nan=False)), output)
        stats = output['performance']
        self.assertEqual(stats['candidates_enumerated'], stats['unique_decoded_series'] + stats['equivalent_candidates_grouped'])
        self.assertGreater(stats['equivalent_candidates_grouped'], 0)
        self.assertTrue(all(stats[k] >= 0 for k in ('decoding_seconds', 'correlation_seconds', 'total_seconds')))
        explicit = analyze_candidate(self.frames, 420, start_bit=16, width_bits=12,
                                     reference=self.reference, run=self.run)
        self.assertGreater(explicit['equivalence']['equivalence_count'], 1)
        self.assertEqual(json.loads(json.dumps(explicit, allow_nan=False)), explicit)
