"""Tiny official-format fixtures; never download data during tests."""

import ast
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.prepare_comma2k19 import convert_can, convert_gnss, load_arrays, prepare, FILES
from canary.observation import read_csv
from tools.run_comma2k19 import experiment


class ConversionTests(unittest.TestCase):
    def test_raw_can_bus_isolation_and_extended_filter(self):
        frames, stats = convert_can([0, 0, 0.1, 0.2], [0x100, 0x100, 0x1234, 0x101],
                                   [bytes(8)]*4, [0, 1, 0, 0])
        self.assertEqual([r[1] for r in frames], [0x100, 0x101])
        self.assertEqual(stats['excluded_other_sources'], 1)
        self.assertEqual(stats['excluded_extended_ids'], 1)
        self.assertEqual(frames[0][2], '00 00 00 00 00 00 00 00')

    def test_gnss_units_and_boot_timestamps(self):
        result = convert_gnss([500, 500.1], [[32, -117, 10, 100000, 8, 90], [32, -117, 0, 100001, 8, 90]])
        self.assertEqual(result, [(500, 36), (500.1, 0)])

    def test_monotonicity_and_invalid_values(self):
        for times in ([1, 0], [0, float('nan')]):
            with self.assertRaises(ValueError):
                convert_can(times, [1, 1], [bytes(8)]*2, [0, 0])
        for times in ([1, 1], [2, 1], [0, float('inf')]):
            with self.assertRaises(ValueError):
                convert_gnss(times, [[0]*6]*2)
        for speed in (-1, float('nan'), float('inf'), 1e308):
            with self.assertRaises(ValueError):
                convert_gnss([0], [[0, 0, speed, 0, 0, 0]])
        for address, data, source in ((-1, bytes(8), 0), (2**29, bytes(8), 0), (1, bytes(7), 0), (1, bytes(8), -1)):
            with self.assertRaises(ValueError):
                convert_can([0], [address], [data], [source])
        with self.assertRaises(ValueError):
            convert_can([0], [], [], [])
        with self.assertRaises(ValueError):
            convert_can([0], [1], [bytes(8)], [1], bus=0)

    def test_production_and_blind_runner_isolation(self):
        root = Path(__file__).resolve().parent.parent
        for path in (root/'canary').rglob('*.py'):
            source = path.read_text(encoding='utf-8')
            for forbidden in ('opendbc', 'comma2k19', 'tools.validate', 'ground_truth'):
                self.assertNotIn(forbidden, source)
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.ImportFrom) and not node.level:
                    self.assertNotIn((node.module or '').split('.')[0], ('tools', 'validation'))
                if isinstance(node, ast.Import):
                    self.assertTrue(all(n.name.split('.')[0] not in ('tools', 'validation') for n in node.names))
        blind = (root/'tools/run_comma2k19.py').read_text(encoding='utf-8')
        for forbidden in ('opendbc', 'ground_truth', 'prepare_comma', 'validate_comma', 'provenance.json'):
            self.assertNotIn(forbidden, blind)

    def test_blind_runner_uses_normalized_csv_and_records_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            can, reference = root/'can.csv', root/'ref.csv'
            can.write_text('timestamp,can_id,data\n'+''.join(
                f'{i},1,{bytes([i, 0, 0, 0, 0, 0, 0, 0]).hex()}\n' for i in range(6)), encoding='utf-8')
            reference.write_text('timestamp,speed_kph\n'+''.join(f'{i},{i*0.2+1}\n' for i in range(6)), encoding='utf-8')
            with patch('tools.prepare_comma2k19.load_arrays', side_effect=AssertionError('blind stage must not read source arrays')):
                result = experiment(can, reference, root/'results', min_samples=3)
            self.assertEqual(result['frame_count'], 6)
            self.assertEqual(result['performance']['candidates_enumerated'], 820)
            self.assertEqual(result['inputs'][str(can)], hashlib.sha256(can.read_bytes()).hexdigest())
            self.assertTrue((root/'results/blind_results.json').exists())
            self.assertTrue((root/'results/report.html').exists())
            json.dumps(result, allow_nan=False)
            with self.assertRaisesRegex(ValueError, 'overwrite'):
                experiment(root/'reconstructed.csv', reference, root, min_samples=3)


@unittest.skipUnless(importlib.util.find_spec('numpy'), 'optional preparation extra not installed')
class NumpyPreparationTests(unittest.TestCase):
    def fixture(self, directory):
        import numpy as np
        # Same NPY dtypes/shapes as the official arrays, including trailing NULs.
        arrays = {'can_t.npy': np.array([10., 10.1, 10.2]), 'can_address.npy': np.array([1, 2, 3], dtype='<i8'),
                  'can_src.npy': np.array([0, 1, 0], dtype='<i8'),
                  'can_data.npy': np.array([b'\xFF\x80', b'\x01', b'\xFE\x00\x01'], dtype='S8'),
                  'gnss_t.npy': np.array([10., 10.1, 10.2]),
                  'gnss_value.npy': np.array([[0, 0, v, 1e9, 0, 0] for v in [10, 11, 12]], dtype='<f8')}
        for name, array in arrays.items():
            np.save(directory/name, array, allow_pickle=False)
        return {name: (FILES[name][0], hashlib.sha256((directory/name).read_bytes()).hexdigest()) for name in FILES}

    def test_storage_preserves_zero_padding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            data = load_arrays(root)[2]
            self.assertEqual(data[0], b'\xFF\x80'+bytes(6))
            self.assertTrue(all(len(p) == 8 for p in data))

    def test_preparation_schema_reproducibility_and_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checksums = self.fixture(root)
            with patch('tools.prepare_comma2k19.FILES', checksums):
                result = prepare(root, root/'out')
                again = prepare(root, root/'out')
            self.assertEqual(result, again)
            self.assertEqual(result['frame_count'], 2)
            self.assertEqual(result['reference_sample_count'], 3)
            self.assertEqual(result['bus_selection']['selected_bus'], 0)
            for name, columns in (('real_can_log.csv', ['timestamp', 'can_id', 'data']),
                                  ('real_speed_reference.csv', ['timestamp', 'speed_kph'])):
                with (root/'out'/name).open(newline='') as stream:
                    self.assertEqual(next(csv.reader(stream)), columns)
            self.assertEqual(len(read_csv(root/'out/real_can_log.csv')), 2)
            json.dumps(result, allow_nan=False)
            with self.assertRaisesRegex(ValueError, 'checksum'):
                prepare(root, root/'out')
