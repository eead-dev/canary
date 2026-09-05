import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from canary.observation import byte_aligned_candidates, read_csv
from simulator.challenges import SCENARIOS, generate_challenges, generate_scenario
from simulator.drive import simulate_drive
from simulator.evaluate_challenges import evaluate_challenges

ROOT = Path(__file__).resolve().parent.parent


class ChallengeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.root = Path(cls.directory.name)
        cls.production_before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in (ROOT / "canary").rglob("*.py")}
        generate_challenges(cls.root)
        cls.results = {r["scenario"]: r for r in evaluate_challenges(cls.root)}

    def metadata(self, name):
        return json.loads((self.root / name / "ground_truth.json").read_text(encoding="utf-8"))

    def reference(self, name):
        with (self.root / name / "reference.csv").open(newline="", encoding="utf-8") as stream:
            return list(csv.DictReader(stream))

    def test_reproducible_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            generate_challenges(Path(directory))
            for name in SCENARIOS:
                for filename in ("can_log.csv", "reference.csv", "ground_truth.json"):
                    with self.subTest(name=name, filename=filename):
                        self.assertEqual((self.root / name / filename).read_bytes(),
                                         (Path(directory) / name / filename).read_bytes())
            generate_scenario("baseline_easy", Path(directory), seed=7)
            self.assertNotEqual((self.root / "baseline_easy/can_log.csv").read_bytes(),
                                (Path(directory) / "baseline_easy/can_log.csv").read_bytes())

    def test_scenario_encodings(self):
        drive = simulate_drive()
        for name in SCENARIOS:
            metadata = self.metadata(name)
            field = metadata["target"]
            frames = read_csv(self.root / name / "can_log.csv")
            self.assertEqual(len(frames), 18000)
            target = [f for f in frames if f.can_id == field["can_id"]]
            self.assertEqual(len(target), 6000)
            decoded_values = []
            for i, frame in enumerate(target):
                if field["width_bits"] == 12:
                    raw = (int.from_bytes(frame.data, "little") >> 19) & 0xFFF
                else:
                    raw = int.from_bytes(frame.data[2:4], field["endian"], signed=field["signed"])
                decoded = raw * field["scale"] + field["offset"]
                decoded_values.append(decoded)
                expected = drive[i].speed_kph
                if name == "unsupported_signed":
                    expected -= 45
                if name == "long_constant_regions":
                    t = i / 100
                    expected = (0 if t < 15 else (t-15)*8 if t < 20 else 40 if t < 45
                                else 40-(t-45)*5 if t < 50 else 15)
                self.assertLessEqual(abs(decoded - expected), field["scale"] / 2 + 1e-10)
            if name == "unsupported_signed":
                self.assertLess(min(decoded_values), 0)
                self.assertGreater(max(decoded_values), 0)
            if name == "long_constant_regions":
                flat = sum(a == b for a, b in zip(decoded_values, decoded_values[1:]))
                self.assertGreater(flat, 4900)

    def test_noise_and_jitter_controls(self):
        baseline = self.reference("baseline_easy")
        noisy = self.reference("noisy_reference")
        differences = [float(b["value"]) - float(a["value"]) for a, b in zip(baseline, noisy)]
        self.assertLessEqual(max(abs(v) for v in differences), 1.500000001)
        self.assertGreater(max(differences) - min(differences), 2)
        self.assertEqual((self.root / "baseline_easy/can_log.csv").read_bytes(),
                         (self.root / "noisy_reference/can_log.csv").read_bytes())
        jitter = self.reference("timestamp_jitter")
        can = read_csv(self.root / "timestamp_jitter/can_log.csv")[::3]
        times = [float(r["timestamp"]) for r in jitter]
        self.assertTrue(all(a < b for a, b in zip(times, times[1:])))
        self.assertTrue(all(abs(t - i/100) <= 0.002000001 for i, t in enumerate(times)))
        self.assertTrue(all(abs(f.timestamp - i/100) <= 0.002000001 for i, f in enumerate(can)))
        self.assertNotEqual(times, [f.timestamp for f in can])

    def test_baseline_and_unusual_recovery(self):
        for name in ("baseline_easy", "unusual_scale_offset"):
            result = self.results[name]
            self.assertTrue(result["recovered"])
            field = self.metadata(name)["target"]
            fit = result["top_fitted"][0]
            # OLS fits quantized raw values; repeated plateaus can bias coefficients.
            self.assertAlmostEqual(fit["scale"], field["scale"], delta=field["scale"] * 1e-4)
            self.assertAlmostEqual(fit["offset"], field["offset"], delta=field["scale"] / 2)
            self.assertLess(fit["rmse"], field["scale"] / 2)

    def test_unsupported_fields_outside_search_space(self):
        space = {(c.byte_offset * 8, c.width_bits, "little", False) for c in byte_aligned_candidates()}
        for name in SCENARIOS:
            if name.startswith("unsupported_"):
                field = self.metadata(name)["target"]
                self.assertNotIn((field["start_bit"], field["width_bits"], field["endian"], field["signed"]), space)
                self.assertFalse(self.results[name]["recovered"])

    def test_evaluation_schema_and_noise_degradation(self):
        required = {"scenario", "expected_support", "seed", "candidates_searched", "candidates_ranked",
                    "top_can_id", "byte_offset", "width_bits", "endian", "signed", "correlation", "r_squared",
                    "aligned_samples", "recovered", "true_field_rank", "reason", "distractor_rank", "top_fitted",
                    "alignment_tolerance", "alignment_mode", "alignment_diagnostics"}
        self.assertEqual(len(self.results), 9)
        for result in self.results.values():
            self.assertEqual(set(result), required)
            self.assertEqual(result["candidates_searched"], 45)
            self.assertEqual(result["alignment_tolerance"], 0.004 if result["scenario"] == "timestamp_jitter" else 0)
            self.assertIn(result["expected_support"], ("supported", "partially_supported", "unsupported"))
            json.dumps(result, allow_nan=False)
        self.assertGreater(self.results["noisy_reference"]["top_fitted"][0]["rmse"],
                           self.results["baseline_easy"]["top_fitted"][0]["rmse"])

    def test_correlated_distractor_encoded(self):
        import math
        frames = read_csv(self.root / "correlated_distractor/can_log.csv")
        target = simulate_drive()
        for sample, frame in zip(target, frames[1::3]):
            raw = int.from_bytes(frame.data[:2], "little")
            expected = max(0, 1.02*sample.speed_kph + 0.8*math.sin(sample.timestamp/3) + 0.3)
            self.assertLessEqual(abs(raw*0.01 - expected), 0.005000001)
        self.assertIsNotNone(self.results["correlated_distractor"]["distractor_rank"])

    def test_ground_truth_isolation_and_unchanged_production(self):
        after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / "canary").rglob("*.py")}
        self.assertEqual(self.production_before, after)
        for path in (ROOT / "canary").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("ground_truth", text)
            self.assertNotIn("simulator", text)
        for name in SCENARIOS:
            self.assertEqual({p.name for p in (self.root / name).iterdir()},
                             {"can_log.csv", "reference.csv", "ground_truth.json"})
            self.assertEqual(list(self.reference(name)[0]), ["timestamp", "value"])


if __name__ == "__main__":
    unittest.main()
