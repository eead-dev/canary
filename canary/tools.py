"""Model-independent structured tools over the deterministic production APIs.

Inputs are parsed Frame lists and (timestamp, value) reference lists. Unknown
IDs and invalid arguments raise ValueError. Undefined statistics use None.
"""

from dataclasses import asdict

from .discovery import align_samples, discover_signal, pearson
from .fitting import fit_linear
from .observation import (
    Candidate, CandidateSpec, Frame, byte_aligned_candidates, candidate_fields, extract_candidate, frame_counts,
    frames_for_id, timestamp_bounds, unique_ids, update_frequencies,
)
from .reference import Series
from .analysis import analysis_run
from .alignment import align_series, configuration


def _frames(frames: list[Frame]) -> None:
    if not isinstance(frames, list) or any(not isinstance(f, Frame) for f in frames):
        raise ValueError("frames must be a list of Frame objects")


def _selected(frames: list[Frame], can_id: int) -> list[Frame]:
    _frames(frames)
    selected = frames_for_id(frames, can_id)
    if not selected:
        raise ValueError(f"CAN ID 0x{can_id:03X} is not present in capture")
    return selected


def _reference(reference: Series) -> None:
    if not isinstance(reference, list) or any(
        not isinstance(pair, (tuple, list)) or len(pair) != 2
        or any(type(v) not in (int, float) for v in pair) for pair in reference
    ):
        raise ValueError("reference must be a list of numeric (timestamp, value) pairs")


def _encoding(can_id: int, candidate: CandidateSpec) -> dict:
    result = {"can_id": can_id, "start_bit": candidate.start_bit, "width_bits": candidate.width_bits,
              "endian": candidate.endian, "signed": candidate.signed}
    if candidate.byte_offset is not None:
        result["byte_offset"] = candidate.byte_offset
    return result


def summarize_capture(frames: list[Frame]) -> dict:
    """Return counts and timestamp bounds/duration in seconds; empty bounds are null."""
    _frames(frames)
    bounds = timestamp_bounds(frames)
    return {"total_frames": len(frames), "unique_can_id_count": len(unique_ids(frames)),
            "first_timestamp": bounds[0] if bounds else None,
            "last_timestamp": bounds[1] if bounds else None,
            "duration_seconds": bounds[1] - bounds[0] if bounds else None}


def list_can_ids(frames: list[Frame]) -> dict:
    """Return IDs in ascending order with frame counts and estimated Hz."""
    _frames(frames)
    frequencies = update_frequencies(frames)
    return {"can_ids": [{"can_id": can_id, "frame_count": count,
                         "update_frequency_hz": frequencies[can_id]}
                        for can_id, count in frame_counts(frames).items()]}


def inspect_can_id(frames: list[Frame], can_id: int, *, run=None) -> dict:
    """Return byte ranges over all selected frames, without interpreting them."""
    selected = _selected(frames, can_id)
    if run is not None and tuple(frames) != run.frames:
        raise ValueError("analysis run does not match capture")
    ranges = []
    for candidate in byte_aligned_candidates():
        if candidate.width_bits == 8 and not candidate.signed:
            values = (run.decoded(Candidate(candidate.byte_offset, 8, can_id=can_id)).values if run is not None
                      else [v for _, v in extract_candidate(selected, can_id, candidate)])
            ranges.append({"byte_offset": candidate.byte_offset, "raw_min": min(values), "raw_max": max(values)})
    return {"can_id": can_id, "frame_count": len(selected),
            "update_frequency_hz": update_frequencies(selected)[can_id],
            "changing_byte_positions": [r["byte_offset"] for r in ranges if r["raw_min"] != r["raw_max"]],
            "byte_ranges": ranges}


def list_candidate_fields(frames: list[Frame], can_id: int) -> dict:
    _selected(frames, can_id)
    return {"can_id": can_id, "candidates": [_encoding(can_id, c) for c in candidate_fields(can_id)]}


def _aligned(frames, can_id, byte_offset, width_bits, reference, tolerance, alignment, endian, signed, start_bit, run):
    selected = _selected(frames, can_id)
    candidate = Candidate(byte_offset, width_bits, endian, signed, can_id, start_bit=start_bit)
    _reference(reference)
    if type(tolerance) not in (int, float):
        raise ValueError("tolerance must be a finite nonnegative number")
    run = analysis_run(frames, reference, tolerance, alignment, run)
    return candidate, run.aligned(candidate).values, run.axis(can_id)[2], asdict(run.axis(can_id)[3]), run

def analyze_candidate(frames: list[Frame], can_id: int, byte_offset: int | None = None, width_bits: int | None = None,
                      reference: Series | None = None, *, include_fit: bool = False,
                      tolerance: float = 0.0, min_samples: int = 3, alignment: str | None = None,
                      endian: str = "little", signed: bool = False, start_bit: int | None = None, run=None) -> dict:
    """Raw ranges cover aligned samples only; fit is included only on request."""
    if type(include_fit) is not bool:
        raise ValueError("include_fit must be boolean")
    candidate, xs, ys, diagnostics, run = _aligned(frames, can_id, byte_offset, width_bits, reference, tolerance, alignment, endian, signed, start_bit, run)
    result = {**_encoding(can_id, candidate), "correlation": run.correlation(candidate, min_samples),
              "aligned_samples": len(xs), "raw_min": min(xs) if xs else None,
              "raw_max": max(xs) if xs else None, "alignment_diagnostics": diagnostics, "equivalence": asdict(run.equivalence(candidate))}
    if include_fit:
        fit = run.fit(candidate, min_samples)
        result["fit"] = asdict(fit) if fit is not None else None
    result.update(run.ambiguity(candidate))
    return result


def search_candidates(frames: list[Frame], reference: Series, *, top_n: int = 10,
                      tolerance: float = 0.0, min_samples: int = 3, alignment: str | None = None, run=None) -> dict:
    _frames(frames)
    _reference(reference)
    if type(top_n) is not int or top_n < 1:
        raise ValueError("top_n must be a positive integer")
    if type(tolerance) not in (int, float):
        raise ValueError("tolerance must be a finite nonnegative number")
    run = analysis_run(frames, reference, tolerance, alignment, run)
    ranked = discover_signal(frames, reference, tolerance=tolerance, min_samples=min_samples, alignment=alignment, run=run)
    # Keep flat ranking intact, while making distinct hypotheses visible even
    # when the first several layouts belong to the same equivalence class.
    hypotheses, seen = [], set()
    for rank, result in enumerate(ranked, 1):
        group = result.equivalence
        if group.representative in seen:
            continue
        seen.add(group.representative)
        hypotheses.append({"rank": rank, "representative": asdict(group.representative),
                           "correlation": result.correlation,
                           "equivalence_count": group.equivalence_count,
                           "equivalent_candidates": [asdict(c) for c in group.equivalent_candidates],
                           "evidence": group.evidence})
        if len(hypotheses) == top_n:
            break
    compared = [CandidateSpec(**h['representative']) for h in hypotheses]
    for hypothesis, candidate in zip(hypotheses, compared):
        hypothesis.update(run.ambiguity(candidate, compared))
    return {"candidates_searched": len(unique_ids(frames)) * len(candidate_fields()),
            "candidates_ranked": len(ranked), "performance": run.statistics(),
            "results": [{"rank": rank, **{k: v for k, v in asdict(r).items() if k != "byte_offset" or v is not None}}
                        for rank, r in enumerate(ranked[:top_n], 1)], "hypotheses": hypotheses}


def fit_candidate(frames: list[Frame], can_id: int, byte_offset: int | None = None, width_bits: int | None = None,
                  reference: Series | None = None, *, tolerance: float = 0.0, min_samples: int = 3, alignment: str | None = None,
                  endian: str = "little", signed: bool = False, start_bit: int | None = None, run=None) -> dict:
    """Fit one explicit field; null fit means insufficient or constant raw data."""
    candidate, xs, ys, diagnostics, run = _aligned(frames, can_id, byte_offset, width_bits, reference, tolerance, alignment, endian, signed, start_bit, run)
    fit = run.fit(candidate, min_samples)
    return {**_encoding(can_id, candidate), "aligned_samples": len(xs),
            "fit": asdict(fit) if fit is not None else None, "alignment_diagnostics": diagnostics,
            "equivalence": asdict(run.equivalence(candidate)), **run.ambiguity(candidate)}
