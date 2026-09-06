import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from validation.validate_comma2k19 import parse_signal, truth_raw, validate_saved
from canary.observation import CandidateSpec


class RealValidationTests(unittest.TestCase):
    DBC = 'BO_ 170 WHEEL_SPEEDS: 8 XXX\n SG_ WHEEL_SPEED_RR : 38|15@0+ (0.01,-67.67) [0|0] "km/h" XXX\n'

    def test_truth_numbering_does_not_expand_production_widths(self):
        field = parse_signal(self.DBC, 'WHEEL_SPEED_RR')
        self.assertEqual((field['can_id'], field['start_bit'], field['width_bits'], field['endian'], field['signed']),
                         (170, 33, 15, 'big', False))
        self.assertEqual(truth_raw((10000 << 16).to_bytes(8, 'big'), field), 10000)
        self.assertEqual(CandidateSpec(33, 15, 'big').width_bits, 15)
        with self.assertRaises(ValueError):
            CandidateSpec(33, 14, 'big')
        with self.assertRaises(ValueError):
            parse_signal(self.DBC, 'UNKNOWN')

    def test_blind_completion_required_before_truth_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blind = root/'blind.json'
            blind.write_text('{}', encoding='utf-8')
            with patch('validation.validate_comma2k19.parse_signal') as parser, self.assertRaisesRegex(ValueError, 'completed blind'):
                validate_saved(blind, root/'can.csv', root/'missing.dbc')
            parser.assert_not_called()

    def test_validation_schema_affine_proxy_and_input_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            can, blind, dbc = root/'can.csv', root/'blind.json', root/'truth.dbc'
            can.write_text('timestamp,can_id,data\n' + ''.join(
                f'{i},170,{(v << 16).to_bytes(8, "big").hex()}\n' for i, v in enumerate([9000, 11000, 14000])), encoding='utf-8')
            dbc.write_text(self.DBC, encoding='utf-8')
            result = {'completed_utc': '2026-09-06T00:00:00Z',
                      'inputs': {str(can): hashlib.sha256(can.read_bytes()).hexdigest()},
                      'top_fitted': [{'can_id': 170, 'start_bit': 34, 'width_bits': 16, 'endian': 'big', 'signed': True,
                                      'scale': 0.0025, 'offset': 96.17}]}
            blind.write_text(json.dumps(result), encoding='utf-8')
            checksum = hashlib.sha256(dbc.read_bytes()).hexdigest()
            with patch('validation.validate_comma2k19.DBC_SHA256', checksum):
                validated = validate_saved(blind, can, dbc)
            self.assertTrue(validated['comparison']['signal_match'])
            self.assertFalse(validated['comparison']['layout_match'])
            self.assertEqual(validated['raw_relationship']['multiplier'], 4)
            self.assertEqual(validated['raw_relationship']['intercept'], -65536)
            self.assertAlmostEqual(validated['comparison']['mapped_scale_error'], 0)
            self.assertAlmostEqual(validated['comparison']['mapped_offset_error'], 0)
            self.assertFalse(validated['comparison']['true_layout_present'])
            target = dict(result['top_fitted'][0], start_bit=33, width_bits=15, signed=False)
            result['top_fitted'].append(target)
            result['ranked_candidates'] = [dict(rank=1, **result['top_fitted'][0]), dict(rank=6, **target)]
            result['distinct_hypotheses'] = [dict(result['top_fitted'][0], rank=1,
                layout_ambiguous=True, ambiguity_reason='affine_equivalent_layouts',
                affine_equivalents=[{'candidate': {k: target[k] for k in ('can_id','start_bit','width_bits','endian','signed')}}])]
            blind.write_text(json.dumps(result), encoding='utf-8')
            with patch('validation.validate_comma2k19.DBC_SHA256', checksum):
                recognized = validate_saved(blind, can, dbc)
            self.assertTrue(recognized['comparison']['true_layout_present'])
            self.assertTrue(recognized['comparison']['signal_value_recovered'])
            self.assertEqual(recognized['comparison']['exact_layout_rank'], 6)
            self.assertFalse(recognized['comparison']['exact_layout_uniquely_identified'])
            self.assertTrue(recognized['comparison']['layout_ambiguous'])
            self.assertEqual(recognized['true_layout_result'], target)
            self.assertEqual(set(validated['discovered']), {'can_id', 'start_bit', 'width_bits', 'endian', 'signed', 'scale', 'offset'})
            json.dumps(validated, allow_nan=False)
            with self.assertRaisesRegex(ValueError, 'DBC checksum'):
                validate_saved(blind, can, dbc)
            can.write_text('timestamp,can_id,data\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'does not match'):
                validate_saved(blind, can, dbc)
