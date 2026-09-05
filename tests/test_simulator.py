import csv
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from simulator.drive import simulate_drive
from simulator.generate import generate_dataset, generate_frames
from simulator.ground_truth import (
    ACCELERATOR, BRAKE_BYTE, BRAKE_CAN_ID, BRAKE_MASK, RPM, SPEED,
)


class EncodingTests(unittest.TestCase):
    def test_speed_known_bytes_and_boundaries(self):
        for value, encoded in ((0, b"\x00\x00"), (123.45, b"\x39\x30"),
                               (655.35, b"\xff\xff")):
            with self.subTest(value=value):
                payload = bytearray(b"\xaa" * 8)
                SPEED.encode(payload, value)
                self.assertEqual(payload[2:4], encoded)
                self.assertEqual(payload[:2] + payload[4:], b"\xaa" * 6)
                self.assertAlmostEqual(SPEED.decode(payload), value)

    def test_scale_and_offset(self):
        field = replace(SPEED, scale=0.25, offset=-10)
        payload = bytearray(8)
        field.encode(payload, 40)
        self.assertEqual(payload[2:4], b"\xc8\x00")
        self.assertEqual(field.decode(payload), 200 * 0.25 - 10)

    def test_quantization(self):
        payload = bytearray(8)
        SPEED.encode(payload, 42.127)
        self.assertEqual(payload[2:4], (4213).to_bytes(2, "little"))
        self.assertLessEqual(abs(SPEED.decode(payload) - 42.127), SPEED.scale / 2)

    def test_invalid_values(self):
        for scale in (0, -1, float("nan"), float("inf")):
            with self.subTest(scale=scale), self.assertRaises(ValueError):
                replace(SPEED, scale=scale)
        for value in (-1, 656, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                SPEED.encode(bytearray(8), value)
        with self.assertRaises(ValueError):
            SPEED.decode(bytes(7))
        with self.assertRaises(ValueError):
            SPEED.encode(bytearray(9), 10)


class GeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.samples = simulate_drive()
        cls.frames = list(generate_frames(cls.samples))

    def test_sampling_and_physics(self):
        samples = self.samples
        self.assertEqual(len(samples), 6000)
        self.assertEqual([s.timestamp for s in samples], [i / 100 for i in range(6000)])
        speeds = [s.speed_kph for s in samples]
        self.assertEqual(min(speeds), 0)
        self.assertGreater(max(speeds) - min(speeds), 30)
        self.assertTrue(all(0 <= s.accelerator_pct <= 100 and s.engine_rpm >= 800
                            and isinstance(s.brake, bool) for s in samples))
        self.assertGreater(samples[1400].speed_kph, samples[400].speed_kph)
        self.assertGreater(samples[1400].engine_rpm, samples[400].engine_rpm)
        coast_drop = samples[1600].speed_kph - samples[1700].speed_kph
        brake_drop = samples[2200].speed_kph - samples[2300].speed_kph
        self.assertGreater(coast_drop, 0)
        self.assertGreater(brake_drop, coast_drop * 3)

    def test_frame_validity_and_all_signals(self):
        self.assertEqual(len(self.frames), 36000)
        self.assertEqual(len({f.can_id for f in self.frames}), 6)
        for index, sample in enumerate(self.samples):
            group = self.frames[index * 6:(index + 1) * 6]
            for frame in group:
                self.assertEqual(len(frame.data), 8)
                self.assertTrue(0 <= frame.can_id <= 0x7FF)
                self.assertEqual(frame.timestamp, sample.timestamp)
            payloads = {f.can_id: f.data for f in group}
            for field, value in ((SPEED, sample.speed_kph),
                                 (ACCELERATOR, sample.accelerator_pct),
                                 (RPM, sample.engine_rpm)):
                self.assertLessEqual(abs(field.decode(payloads[field.can_id]) - value),
                                     field.scale / 2 + 1e-10)
            self.assertEqual(bool(payloads[BRAKE_CAN_ID][BRAKE_BYTE] & BRAKE_MASK),
                             sample.brake)

    def test_reproducible_noise(self):
        self.assertEqual(self.frames, list(generate_frames(self.samples)))
        changed = list(generate_frames(self.samples, seed=7))
        self.assertNotEqual(self.frames[0].data, changed[0].data)
        self.assertEqual(SPEED.decode(self.frames[0].data), SPEED.decode(changed[0].data))

    def test_csv_schema_counts_and_configurable_speed(self):
        with tempfile.TemporaryDirectory() as directory:
            can_path, reference_path = generate_dataset(Path(directory), speed_scale=0.02)
            self.assertEqual({p.name for p in Path(directory).iterdir()},
                             {"can_log.csv", "speed_reference.csv"})
            with can_path.open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(reader.fieldnames, ["timestamp", "can_id", "data"])
                rows = list(reader)
            with reference_path.open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(reader.fieldnames, ["timestamp", "speed_kph"])
                reference = list(reader)
            self.assertEqual(len(rows), 36000)
            self.assertEqual(len(reference), 6000)
            speed_rows = []
            for row in rows:
                self.assertRegex(row["data"], r"^[0-9A-F]{2}( [0-9A-F]{2}){7}$")
                self.assertEqual(len(bytes.fromhex(row["data"])), 8)
                self.assertTrue(0 <= int(row["can_id"], 16) <= 0x7FF)
                if int(row["can_id"], 16) == SPEED.can_id:
                    speed_rows.append(row)
            field = replace(SPEED, scale=0.02)
            for row, ref in zip(speed_rows, reference, strict=True):
                self.assertEqual(row["timestamp"], ref["timestamp"])
                self.assertLessEqual(abs(field.decode(bytes.fromhex(row["data"]))
                                         - float(ref["speed_kph"])), 0.010001)


if __name__ == "__main__":
    unittest.main()
