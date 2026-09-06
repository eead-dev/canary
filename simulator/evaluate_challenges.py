"""Evaluate the unchanged production engine; judge recovery using isolated truth."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
from time import perf_counter

from canary.discovery import discover_signal
from canary.fitting import fit_ranked
from canary.observation import CandidateSpec, candidate_fields, read_csv, unique_ids
from canary.reference import read_reference
from canary.analysis import AnalysisRun

from .challenges import DEFAULT_ROOT, SCENARIOS, generate_challenges


def matches_field(candidate, field: dict) -> bool:
    return (candidate.can_id == field["can_id"] and candidate.start_bit == field["start_bit"]
            and candidate.width_bits == field["width_bits"] and candidate.endian == field["endian"]
            and candidate.signed == field["signed"])


def evaluate_scenario(directory: Path) -> dict:
    started = perf_counter()
    frames = read_csv(directory / "can_log.csv")
    reference = read_reference(directory / "reference.csv", "value")
    # Both clocks jitter by at most 2 ms: relative displacement is at most 4 ms.
    mode, tolerance = ("nearest", 0.004) if directory.name == "timestamp_jitter" else ("exact", 0.0)
    run = AnalysisRun(frames, reference, alignment=mode, tolerance=tolerance)
    ranked = discover_signal(frames, reference, alignment=mode, tolerance=tolerance, run=run)
    fitted = fit_ranked(frames, reference, ranked[:5], alignment=mode, tolerance=tolerance, run=run)
    best = ranked[0] if ranked else None
    ambiguity = (run.ambiguity(CandidateSpec(best.start_bit, best.width_bits, best.endian, best.signed, best.can_id))
                 if best else None)
    # Ground truth is read only after engine execution and never passed into it.
    metadata = json.loads((directory / "ground_truth.json").read_text(encoding="utf-8"))
    field = metadata["target"]
    top = ranked[0] if ranked else None
    recovered = top is not None and matches_field(top, field)
    members = ([top.equivalence.representative, *top.equivalence.equivalent_candidates] if top else [])
    affine_members = [CandidateSpec(**e['candidate']) for e in ambiguity['affine_equivalents']] if ambiguity else []
    signal_value_recovered = any(matches_field(c, field) for c in [*members, *affine_members])
    layout_ambiguous = bool(ambiguity and ambiguity['layout_ambiguous'])
    exact_layout_recovered = recovered and not layout_ambiguous
    true_rank = next((i for i, candidate in enumerate(ranked, 1) if matches_field(candidate, field)), None)
    if signal_value_recovered and layout_ambiguous:
        reason = "signal values recovered; observationally equivalent layouts, exact layout unresolved"
    elif recovered:
        reason = "correct complete field ranked #1"
    elif field["width_bits"] not in (8, 12, 15, 16) or not 0 <= field["start_bit"] <= 64-field["width_bits"]:
        reason = "target outside supported bit-field search space"
    elif top is None:
        reason = "no ranked candidates: insufficient exact matches or undefined correlation"
    else:
        reason = f"another field ranked #1; true field rank is {true_rank}"
    distractor = metadata.get("distractor")
    distractor_rank = next((i for i, c in enumerate(ranked, 1) if matches_field(c, distractor)), None) if distractor else None
    comparison = None
    if directory.name == "unsupported_big_endian":
        comparison = {}
        for label, predicate in (
            ("correct", lambda c: matches_field(c, field)),
            ("partial_byte", lambda c: c.can_id == field["can_id"] and c.start_bit == field["start_bit"]
             and c.width_bits == 8 and not c.signed),
        ):
            entry = next(((i, c) for i, c in enumerate(ranked, 1) if predicate(c)), None)
            if entry:
                rank, candidate = entry
                fit = fit_ranked(frames, reference, [candidate], alignment=mode, tolerance=tolerance, run=run)[0]
                comparison[label] = {"rank": rank, **asdict(fit)}
    expected = metadata["expected_support"]
    if field["width_bits"] in (8, 12, 15, 16) and 0 <= field["start_bit"] <= 64-field["width_bits"] and expected == "unsupported":
        expected = "supported"
    performance = run.statistics()
    performance["total_seconds"] = perf_counter() - started
    return {
        "scenario": metadata["scenario"], "seed": metadata["seed"],
        "expected_support": expected,
        "candidates_searched": len(unique_ids(frames)) * len(candidate_fields()),
        "candidates_ranked": len(ranked), "top_can_id": top.can_id if top else None,
        "byte_offset": top.byte_offset if top else None, "start_bit": top.start_bit if top else None,
        "width_bits": top.width_bits if top else None,
        "endian": top.endian if top else None, "signed": top.signed if top else None,
        "correlation": top.correlation if top else None,
        "r_squared": fitted[0].r_squared if fitted else None,
        "aligned_samples": top.aligned_samples if top else 0,
        "recovered": recovered, "true_field_rank": true_rank, "reason": reason,
        "distractor_rank": distractor_rank, "top_fitted": [asdict(f) for f in fitted],
        "alignment_tolerance": tolerance, "alignment_mode": mode,
        "alignment_diagnostics": asdict(top.alignment_diagnostics) if top else None,
        "encoding_comparison": comparison,
        "signal_value_recovered": signal_value_recovered,
        "exact_layout_recovered": exact_layout_recovered, "layout_ambiguous": layout_ambiguous,
        "performance": performance,
        "ambiguity": ambiguity,
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
    print(f"Candidates per CAN ID: {len(candidate_fields())}")
    print("Scenario | Searched | Unique series/classes | Grouped | Constants | Decode s | Correlation s | Total s | Signal value recovered | Exact layout recovered | Layout ambiguous | Notes")
    for row in results:
        fmt = lambda v: "N/A" if v is None else f"{v:.9f}"
        can_id = "N/A" if row["top_can_id"] is None else f"0x{row['top_can_id']:03X}"
        stats = row['performance']
        print(f"{row['scenario']} | {stats['candidates_enumerated']} | {stats['unique_decoded_series']} | "
              f"{stats['equivalent_candidates_grouped']} | {stats['constant_candidates_skipped']} | "
              f"{stats['decoding_seconds']:.3f} | {stats['correlation_seconds']:.3f} | {stats['total_seconds']:.3f} | "
              f"{row['signal_value_recovered']} | {row['exact_layout_recovered']} | {row['layout_ambiguous']} | {row['reason']}")
    print(f"Total scenario runtime: {sum(r['performance']['total_seconds'] for r in results):.3f} s")
    print(f"Detailed results: {output}")


if __name__ == "__main__":
    main()
