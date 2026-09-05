"""Rank raw CAN fields against a user-supplied reference CSV."""

import argparse
from pathlib import Path

from .discovery import discover_signal
from .fitting import fit_ranked, write_reconstruction
from .observation import byte_aligned_candidates, read_csv, unique_ids
from .reference import read_reference
from .reporting import candidate_details, equation, write_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("can_log", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--value-column", required=True)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--timestamp-tolerance", "--tolerance", dest="tolerance", type=float, default=0.0, help="timestamp tolerance in seconds")
    parser.add_argument("--alignment", choices=("exact", "nearest"), help="default exact; legacy nonzero tolerance selects nearest")
    parser.add_argument("--min-samples", type=int, default=3)
    parser.add_argument("--fit", action="store_true", help="fit physical scale and offset")
    parser.add_argument("--output-reconstruction", type=Path, help="export best fit (requires --fit)")
    parser.add_argument("--report", type=Path, help="write self-contained HTML report (requires --fit)")
    args = parser.parse_args()
    if args.top < 1:
        parser.error("--top must be positive")
    if args.output_reconstruction and not args.fit:
        parser.error("--output-reconstruction requires --fit")
    if args.report and not args.fit:
        parser.error("--report requires --fit")
    if args.report and args.report.resolve() in (
            args.can_log.resolve(), args.reference.resolve(),
            args.output_reconstruction.resolve() if args.output_reconstruction else None):
        parser.error("report output must differ from inputs and reconstruction output")
    if args.output_reconstruction and args.output_reconstruction.resolve() in (
            args.can_log.resolve(), args.reference.resolve()):
        parser.error("reconstruction output must differ from input files")
    try:
        frames = read_csv(args.can_log)
        reference = read_reference(args.reference, args.value_column)
        results = discover_signal(frames, reference, tolerance=args.tolerance, min_samples=args.min_samples, alignment=args.alignment)
        displayed = results[:args.top]
        if args.fit:
            displayed = fit_ranked(frames, reference, displayed, tolerance=args.tolerance,
                                   min_samples=args.min_samples, alignment=args.alignment)
        if args.output_reconstruction:
            if not displayed:
                raise ValueError("no fitted candidate available for reconstruction")
            write_reconstruction(args.output_reconstruction, frames, reference, displayed[0],
                                 tolerance=args.tolerance, alignment=args.alignment)
        if args.report:
            write_report(args.report, frames, reference, displayed, args.value_column,
                         tolerance=args.tolerance, alignment=args.alignment)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    searched = len(unique_ids(frames)) * len(byte_aligned_candidates())
    print(f"Reference: {args.value_column}")
    if args.fit:
        print(f"CAN frames: {len(frames):,}\nUnique CAN IDs: {len(unique_ids(frames))}")
    print(f"Candidates searched: {searched}")
    print(f"Candidates per CAN ID: {len(byte_aligned_candidates())}")
    print(f"Candidates ranked: {len(results)}")
    print(f"Skipped (constant or insufficient aligned samples): {searched - len(results)}")
    if displayed and displayed[0].alignment_diagnostics:
        diagnostic = displayed[0].alignment_diagnostics
        print(f"Alignment (best): {diagnostic.matched_sample_count}/{diagnostic.candidate_sample_count} matched; "
              f"{diagnostic.unmatched_sample_count} unmatched; ratio {diagnostic.match_ratio:.6f}")
        print(f"Timestamp error (seconds): mean {diagnostic.mean_absolute_timestamp_error:.9f}; "
              f"max {diagnostic.max_absolute_timestamp_error:.9f}")
    if args.fit and displayed:
        print(f"Aligned samples (best): {displayed[0].aligned_samples:,}")
        print("\n=== BEST CANDIDATE ===")
        for label, value in candidate_details(displayed[0]):
            print(f"{label + ':':<22}{value}")
        print(equation(displayed[0]))
        print("\n=== RANKED TOP CANDIDATES ===")
    for rank, result in enumerate(displayed, 1):
        print(f"\n#{rank}\nCAN ID:       0x{result.can_id:03X}")
        print(f"Byte offset:  {result.byte_offset}\nLength:       {result.width_bits} bits")
        print(f"Endian:       {result.endian}\nSigned:       {'yes' if result.signed else 'no'}")
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
    if args.report:
        print(f"Report written: {args.report}")


if __name__ == "__main__":
    main()
