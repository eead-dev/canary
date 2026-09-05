"""Inspect CAN CSV traffic: python -m canary.inspect PATH."""

import argparse
from pathlib import Path

from .observation import frame_counts, read_csv, timestamp_bounds, update_frequencies


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        frames = read_csv(args.path)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    bounds = timestamp_bounds(frames)
    counts = frame_counts(frames)
    frequencies = update_frequencies(frames)
    print(f"Total frames: {len(frames):,}")
    if bounds is None:
        print("First timestamp: N/A\nLast timestamp: N/A\nCapture duration: N/A")
    else:
        first, last = bounds
        print(f"First timestamp: {first:.6f} s")
        print(f"Last timestamp: {last:.6f} s")
        print(f"Capture duration: {last - first:.6f} s")
    print("Unique CAN IDs: " + (", ".join(f"0x{i:03X}" for i in counts) or "none"))
    for can_id, count in counts.items():
        hz = frequencies[can_id]
        frequency = "N/A" if hz is None else f"{hz:.2f} Hz"
        print(f"0x{can_id:03X}: {count:,} frames, estimated frequency {frequency}")


if __name__ == "__main__":
    main()
