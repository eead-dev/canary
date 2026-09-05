"""Evaluate the unchanged production engine; judge recovery using isolated truth."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from canary.discovery import discover_signal
from canary.fitting import fit_ranked
from canary.observation import byte_aligned_candidates, read_csv, unique_ids
from canary.reference import read_reference

from .challenges import DEFAULT_ROOT, SCENARIOS, generate_challenges


def matches_field(candidate, field: dict) -> bool:
    return (candidate.can_id == field["can_id"] and candidate.byte_offset * 8 == field["start_bit"]
            and candidate.width_bits == field["width_bits"] and candidate.endian == field["endian"]
            and candidate.signed == field["signed"])


def evaluate_scenario(directory: Path) -> dict:
    frames = read_csv(directory / "can_log.csv")
    reference = read_reference(directory / "reference.csv", "value")
    # Both clocks jitter by at most 2 ms: relative displacement is at most 4 ms.
    mode, tolerance = ("nearest", 0.004) if directory.name == "timestamp_jitter" else ("exact", 0.0)
    ranked = discover_signal(frames, reference, alignment=mode, tolerance=tolerance)
    fitted = fit_ranked(frames, reference, ranked[:5], alignment=mode, tolerance=tolerance)
    # Ground truth is read only after engine execution and never passed into it.
    metadata = json.loads((directory / "ground_truth.json").read_text(encoding="utf-8"))
    field = metadata["target"]
    top = ranked[0] if ranked else None
    recovered = top is not None and matches_field(top, field)
    true_rank = next((i for i, candidate in enumerate(ranked, 1) if matches_field(candidate, field)), None)
    if recovered:
        reason = "correct complete field ranked #1"
    elif field["endian"] != "little":
        reason = "big-endian target outside search space; partial/proxy fields may correlate"
    elif field["signed"]:
        reason = "signed target outside search space; unsigned interpretation is not recovery"
    elif field["start_bit"] % 8 or field["width_bits"] not in (8, 16):
        reason = "non-byte-aligned 12-bit target outside search space"
    elif top is None:
        reason = "no ranked candidates: insufficient exact matches or undefined correlation"
    else:
        reason = f"another field ranked #1; true field rank is {true_rank}"
    distractor = metadata.get("distractor")
    distractor_rank = next((i for i, c in enumerate(ranked, 1) if matches_field(c, distractor)), None) if distractor else None
    return {
        "scenario": metadata["scenario"], "seed": metadata["seed"],
        "expected_support": metadata["expected_support"],
        "candidates_searched": len(unique_ids(frames)) * len(byte_aligned_candidates()),
        "candidates_ranked": len(ranked), "top_can_id": top.can_id if top else None,
        "byte_offset": top.byte_offset if top else None, "width_bits": top.width_bits if top else None,
        "endian": top.endian if top else None, "signed": top.signed if top else None,
        "correlation": top.correlation if top else None,
        "r_squared": fitted[0].r_squared if fitted else None,
        "aligned_samples": top.aligned_samples if top else 0,
        "recovered": recovered, "true_field_rank": true_rank, "reason": reason,
        "distractor_rank": distractor_rank, "top_fitted": [asdict(f) for f in fitted],
        "alignment_tolerance": tolerance, "alignment_mode": mode,
        "alignment_diagnostics": asdict(top.alignment_diagnostics) if top else None,
    }


def evaluate_challenges(root: Path = DEFAULT_ROOT) -> list[dict]:
    return [evaluate_scenario(Path(root) / name) for name in SCENARIOS]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--regenerate", action="store_true", help="overwrite all challenge fixtures")
    parser.add_argument("--seed", type=int, default=42, help="seed when generating fixtures")
    args = parser.parse_args()
    files = [args.dataset_dir / name / filename for name in SCENARIOS
             for filename in ("can_log.csv", "reference.csv", "ground_truth.json")]
    try:
        if args.regenerate or not any(path.exists() for path in files):
            generate_challenges(args.dataset_dir, seed=args.seed)
        elif not all(path.exists() for path in files):
            raise ValueError("incomplete challenge suite; use --regenerate to replace it")
        results = evaluate_challenges(args.dataset_dir)
        output = args.dataset_dir / "evaluation.json"
        output.write_text(json.dumps(results, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print("Scenario | Expected | Searched | Top ID | Byte | Bits | Pearson r | R-squared | Samples | Recovered | Notes")
    for row in results:
        fmt = lambda v: "N/A" if v is None else f"{v:.9f}"
        can_id = "N/A" if row["top_can_id"] is None else f"0x{row['top_can_id']:03X}"
        print(f"{row['scenario']} | {row['expected_support']} | {row['candidates_searched']} | {can_id} | "
              f"{row['byte_offset']} | {row['width_bits']} | {fmt(row['correlation'])} | {fmt(row['r_squared'])} | "
              f"{row['aligned_samples']} | {'yes' if row['recovered'] else 'no'} | {row['reason']}")
    print(f"Detailed results: {output}")


if __name__ == "__main__":
    main()
