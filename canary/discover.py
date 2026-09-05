"""Rank raw CAN fields against a user-supplied reference CSV."""

import argparse
from pathlib import Path

from .discovery import discover_signal
from .fitting import fit_ranked, write_reconstruction
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
    parser.add_argument("--fit", action="store_true", help="fit physical scale and offset")
    parser.add_argument("--output-reconstruction", type=Path, help="export best fit (requires --fit)")
    args = parser.parse_args()
    if args.top < 1:
        parser.error("--top must be positive")
    if args.output_reconstruction and not args.fit:
        parser.error("--output-reconstruction requires --fit")
    if args.output_reconstruction and args.output_reconstruction.resolve() in (
            args.can_log.resolve(), args.reference.resolve()):
        parser.error("reconstruction output must differ from input files")
    try:
        frames = read_csv(args.can_log)
        reference = read_reference(args.reference, args.value_column)
        results = discover_signal(frames, reference, tolerance=args.tolerance, min_samples=args.min_samples)
        displayed = results[:args.top]
        if args.fit:
            displayed = fit_ranked(frames, reference, displayed, tolerance=args.tolerance,
                                   min_samples=args.min_samples)
        if args.output_reconstruction:
            if not displayed:
                raise ValueError("no fitted candidate available for reconstruction")
            write_reconstruction(args.output_reconstruction, frames, reference, displayed[0],
                                 tolerance=args.tolerance)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    searched = len(unique_ids(frames)) * len(byte_aligned_candidates())
    print(f"Reference: {args.value_column}")
    print(f"Candidates searched: {searched}")
    print(f"Candidates ranked: {len(results)}")
    print(f"Skipped (constant or insufficient aligned samples): {searched - len(results)}")
    for rank, result in enumerate(displayed, 1):
        print(f"\n#{rank}\nCAN ID:       0x{result.can_id:03X}")
        print(f"Byte offset:  {result.byte_offset}\nLength:       {result.width_bits} bits")
        print(f"Endian:       {result.endian}\nSigned:       no")
        print(f"Correlation:  {result.correlation:.12f}\nSamples:      {result.aligned_samples}")
        if args.fit:
            print(f"Scale:        {result.scale:.12g}\nOffset:       {result.offset:.12g}")
            print(f"RMSE:         {result.rmse:.12g}\nMAE:          {result.mae:.12g}")
            score = "N/A" if result.r_squared is None else f"{result.r_squared:.12g}"
            print(f"R-squared:    {score}")
    if not results:
        print("No candidates have a defined correlation.")
    if args.output_reconstruction:
        print(f"Reconstruction written: {args.output_reconstruction}")


if __name__ == "__main__":
    main()
