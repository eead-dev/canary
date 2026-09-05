"""Generate controlled observations and separate evaluator-only metadata."""

import argparse
import csv
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import random

from .drive import simulate_drive

DEFAULT_ROOT = Path(__file__).resolve().parent.parent / "datasets" / "challenges"
SCENARIOS = (
    "baseline_easy", "noisy_reference", "timestamp_jitter", "correlated_distractor",
    "unusual_scale_offset", "long_constant_regions", "unsupported_big_endian",
    "unsupported_signed", "unsupported_bit_offset",
)


@dataclass(frozen=True)
class HiddenField:
    can_id: int = 0x1A4
    start_bit: int = 16
    width_bits: int = 16
    endian: str = "little"
    signed: bool = False
    scale: float = 0.01
    offset: float = 0.0


def scenario_field(name: str) -> HiddenField:
    if name not in SCENARIOS:
        raise ValueError(f"unknown challenge scenario: {name}")
    if name == "unusual_scale_offset":
        return HiddenField(scale=0.037, offset=-12.5)
    if name == "unsupported_big_endian":
        return HiddenField(endian="big")
    if name == "unsupported_signed":
        return HiddenField(signed=True)
    if name == "unsupported_bit_offset":
        return HiddenField(start_bit=19, width_bits=12, scale=0.025)
    return HiddenField()


def encode_hidden(payload: bytearray, value: float, field: HiddenField) -> None:
    """Fixture encoder only; these formats are NOT added to production decoding.

    start_bit uses LSB0 for little-endian fields. For the byte-aligned big-endian
    fixture it denotes the first storage byte times eight, not DBC Motorola bits.
    """
    raw = round((value - field.offset) / field.scale)
    low = -(1 << (field.width_bits - 1)) if field.signed else 0
    high = (1 << (field.width_bits - int(field.signed))) - 1
    if not low <= raw <= high:
        raise ValueError("challenge physical value exceeds field range")
    if field.start_bit % 8 == 0 and field.width_bits % 8 == 0:
        start, width = field.start_bit // 8, field.width_bits // 8
        payload[start:start + width] = raw.to_bytes(width, field.endian, signed=field.signed)
    else:
        mask = ((1 << field.width_bits) - 1) << field.start_bit
        word = int.from_bytes(payload, "little")
        word = (word & ~mask) | ((raw & ((1 << field.width_bits) - 1)) << field.start_bit)
        payload[:] = word.to_bytes(8, "little")


def target_value(name: str, timestamp: float, speed: float) -> float:
    if name == "unsupported_signed":
        return speed - 45.0
    if name == "long_constant_regions":
        if timestamp < 15:
            return 0.0
        if timestamp < 20:
            return (timestamp - 15) * 8
        if timestamp < 45:
            return 40.0
        if timestamp < 50:
            return 40 - (timestamp - 45) * 5
        return 15.0
    return speed


def generate_scenario(name: str, root: Path = DEFAULT_ROOT, *, seed: int = 42) -> Path:
    field = scenario_field(name)
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    # Independent RNG streams keep payloads identical across reference-only variants.
    payload_rng, noise_rng = random.Random(seed), random.Random(seed + 1)
    can_time_rng, ref_time_rng = random.Random(seed + 2), random.Random(seed + 3)
    directory = Path(root) / name
    directory.mkdir(parents=True, exist_ok=True)
    distractor = HiddenField(can_id=0x316, start_bit=0)
    with (directory / "can_log.csv").open("w", newline="", encoding="utf-8") as can_stream, (
        directory / "reference.csv"
    ).open("w", newline="", encoding="utf-8") as reference_stream:
        can_writer, ref_writer = csv.writer(can_stream), csv.writer(reference_stream)
        can_writer.writerow(("timestamp", "can_id", "data"))
        ref_writer.writerow(("timestamp", "value"))
        for sample in simulate_drive():
            t = sample.timestamp
            value = target_value(name, t, sample.speed_kph)
            observed = value
            if name == "noisy_reference":
                observed += max(-1.5, min(1.5, noise_rng.gauss(0, 0.5)))
            can_t, ref_t = t, t
            if name == "timestamp_jitter":
                can_t += can_time_rng.uniform(-0.002, 0.002)
                ref_t += ref_time_rng.uniform(-0.002, 0.002)
            payloads = {can_id: bytearray(payload_rng.randbytes(8)) for can_id in (0x1A4, 0x316, 0x427)}
            encode_hidden(payloads[field.can_id], value, field)
            if name == "correlated_distractor":
                distractor_value = max(0, 1.02 * value + 0.8 * math.sin(t / 3) + 0.3)
                encode_hidden(payloads[distractor.can_id], distractor_value, distractor)
            for can_id, payload in payloads.items():
                can_writer.writerow((f"{can_t:.9f}", f"0x{can_id:03X}", payload.hex(" ").upper()))
            ref_writer.writerow((f"{ref_t:.9f}", f"{observed:.9f}"))
    expected = "unsupported" if name.startswith("unsupported_") else (
        "partially_supported" if name == "timestamp_jitter" else "supported")
    metadata = {
        "scenario": name, "seed": seed, "expected_support": expected,
        "duration_seconds": 60, "sample_rate_hz": 100, "sample_count": 6000,
        "reference_column": "value", "target": asdict(field),
        "bit_numbering": "LSB0 for little-endian; big-endian start_bit identifies first storage byte",
        "reference_noise": {"distribution": "clipped Gaussian", "stddev": 0.5, "bound": 1.5}
                           if name == "noisy_reference" else None,
        "timestamp_jitter_seconds": 0.002 if name == "timestamp_jitter" else 0.0,
        "distractor": asdict(distractor) if name == "correlated_distractor" else None,
        "distractor_formula": "max(0, 1.02*target + 0.8*sin(t/3) + 0.3)"
                              if name == "correlated_distractor" else None,
        "rng_stream_seeds": {"payload": seed, "noise": seed+1, "can_time": seed+2, "reference_time": seed+3},
    }
    (directory / "ground_truth.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return directory


def generate_challenges(root: Path = DEFAULT_ROOT, *, seed: int = 42) -> list[Path]:
    return [generate_scenario(name, root, seed=seed) for name in SCENARIOS]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    for path in generate_challenges(args.output_dir, seed=args.seed):
        print(f"Generated {path}")


if __name__ == "__main__":
    main()
