"""Rank raw CAN fields against a user-supplied reference CSV."""

import argparse
from pathlib import Path

from .discovery import discover_signal
from .observation import byte_aligned_candidates, read_csv, unique_ids
from .reference import read_reference


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("can_log", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--value-column", required=True)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--tolerance", type=float, default=0.0, help="timestamp tolerance in seconds")
    parser.add_argument("--min-samples", type=int, default=3)
    args = parser.parse_args()
    if args.top < 1:
        parser.error("--top must be positive")
    try:
        frames = read_csv(args.can_log)
        reference = read_reference(args.reference, args.value_column)
        results = discover_signal(frames, reference, tolerance=args.tolerance, min_samples=args.min_samples)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    searched = len(unique_ids(frames)) * len(byte_aligned_candidates())
    print(f"Reference: {args.value_column}")
    print(f"Candidates searched: {searched}")
    print(f"Candidates ranked: {len(results)}")
    print(f"Skipped (constant or insufficient aligned samples): {searched - len(results)}")
    for rank, result in enumerate(results[:args.top], 1):
        print(f"\n#{rank}\nCAN ID:       0x{result.can_id:03X}")
        print(f"Byte offset:  {result.byte_offset}\nLength:       {result.width_bits} bits")
        print(f"Endian:       {result.endian}\nSigned:       no")
        print(f"Correlation:  {result.correlation:.12f}\nSamples:      {result.aligned_samples}")
    if not results:
        print("No candidates have a defined correlation.")


if __name__ == "__main__":
    main()
