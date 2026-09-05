"""Regenerate observation CSVs: python -m simulator.generate."""

import argparse
import csv
from dataclasses import dataclass, replace
from pathlib import Path
import random
from collections.abc import Iterator

from .drive import Sample, simulate_drive
from .ground_truth import (
    ACCELERATOR, BRAKE_BYTE, BRAKE_CAN_ID, BRAKE_MASK, NOISE_IDS, RPM, SPEED,
)

DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "datasets" / "synthetic"


@dataclass(frozen=True)
class Frame:
    timestamp: float
    can_id: int
    data: bytes


def generate_frames(samples: list[Sample], *, speed_scale: float = 0.01,
                    seed: int = 42) -> Iterator[Frame]:
    """Generate six frames per sample with reproducible background traffic."""
    speed_field = replace(SPEED, scale=speed_scale)
    rng = random.Random(seed)
    for index, sample in enumerate(samples):
        payloads = {
            can_id: bytearray(rng.randbytes(8))
            for can_id in (SPEED.can_id, ACCELERATOR.can_id, RPM.can_id, *NOISE_IDS)
        }
        speed_field.encode(payloads[SPEED.can_id], sample.speed_kph)
        ACCELERATOR.encode(payloads[ACCELERATOR.can_id], sample.accelerator_pct)
        RPM.encode(payloads[RPM.can_id], sample.engine_rpm)
        payloads[BRAKE_CAN_ID][BRAKE_BYTE] &= ~BRAKE_MASK
        if sample.brake:
            payloads[BRAKE_CAN_ID][BRAKE_BYTE] |= BRAKE_MASK
        # An unrelated rolling counter amongst otherwise random background bytes.
        payloads[NOISE_IDS[0]][0:2] = (index % 65536).to_bytes(2, "little")
        for can_id, payload in payloads.items():
            yield Frame(sample.timestamp, can_id, bytes(payload))


def generate_dataset(output_dir: Path = DEFAULT_OUTPUT, *, speed_scale: float = 0.01,
                     seed: int = 42) -> tuple[Path, Path]:
    samples = simulate_drive()
    # Validate all encodings before overwriting observation files.
    frames = list(generate_frames(samples, speed_scale=speed_scale, seed=seed))
    output_dir.mkdir(parents=True, exist_ok=True)
    can_path = output_dir / "can_log.csv"
    reference_path = output_dir / "speed_reference.csv"
    with can_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("timestamp", "can_id", "data"))
        for frame in frames:
            writer.writerow((f"{frame.timestamp:.2f}", f"0x{frame.can_id:03X}",
                             frame.data.hex(" ").upper()))
    with reference_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("timestamp", "speed_kph"))
        for sample in samples:
            writer.writerow((f"{sample.timestamp:.2f}", f"{sample.speed_kph:.6f}"))
    return can_path, reference_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--speed-scale", type=float, default=0.01,
                        help="km/h per unsigned raw unit (default: 0.01)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    try:
        paths = generate_dataset(args.output_dir, speed_scale=args.speed_scale, seed=args.seed)
    except ValueError as exc:
        parser.error(str(exc))
    for path in paths:
        print(f"Generated {path} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
