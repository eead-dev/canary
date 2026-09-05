"""Deterministic raw-field correlation against a supplied numeric series."""

from dataclasses import dataclass
import math

from .observation import Frame, byte_aligned_candidates, extract_candidate, frames_for_id, unique_ids
from .reference import Series, validate_reference
from .alignment import AlignmentDiagnostics, align_series, configuration


def align_samples(candidate: Series, reference: Series, *, tolerance: float = 0.0, alignment: str | None = None
                  ) -> tuple[list[float], list[float]]:
    """Return aligned raw/reference values using timestamp matching."""
    rows = align_observations(candidate, reference, tolerance=tolerance, alignment=alignment)
    return [x for _, x, _ in rows], [y for _, _, y in rows]


def align_observations(candidate: Series, reference: Series, *, tolerance: float = 0.0, alignment: str | None = None
                       ) -> list[tuple[float, float, float]]:
    """Greedy nearest matching in time order, without reuse or interpolation.

    Ties prefer the earlier reference timestamp. Matches are monotonic; skipped
    reference samples cannot be reused later. Duplicate candidate timestamps
    retain input order. Tolerance is an inclusive distance in seconds.
    """
    return align_series(candidate, reference, configuration(alignment, tolerance)).rows


def pearson(xs: list[float], ys: list[float], *, min_samples: int = 3) -> float | None:
    """Signed Pearson r, or None for insufficient samples or zero variance."""
    if type(min_samples) is not int or min_samples < 3:
        raise ValueError("min_samples must be an integer of at least 3")
    if len(xs) != len(ys):
        raise ValueError("Pearson inputs must have equal lengths")
    if any(not math.isfinite(v) for values in (xs, ys) for v in values):
        raise ValueError("Pearson inputs must be finite")
    if len(xs) < min_samples:
        return None
    centered = []
    for values in (xs, ys):
        # Positive normalization avoids overflow for large finite inputs.
        magnitude = max(abs(v) for v in values)
        normalized = [v / magnitude for v in values] if magnitude else [0.0] * len(values)
        mean = math.fsum(normalized) / len(values)
        centered.append([v - mean for v in normalized])
    dx, dy = centered
    xx, yy = math.fsum(v * v for v in dx), math.fsum(v * v for v in dy)
    if xx == 0 or yy == 0:
        return None
    r = math.fsum(x * y for x, y in zip(dx, dy)) / math.sqrt(xx) / math.sqrt(yy)
    return max(-1.0, min(1.0, r))


@dataclass(frozen=True)
class DiscoveryResult:
    can_id: int
    byte_offset: int
    width_bits: int
    correlation: float
    aligned_samples: int
    endian: str = "little"
    signed: bool = False
    alignment_diagnostics: AlignmentDiagnostics | None = None


def discover_signal(can_log: list[Frame], reference_series: Series, *,
                    tolerance: float = 0.0, min_samples: int = 3, alignment: str | None = None) -> list[DiscoveryResult]:
    """Search every supported field; omit candidates with undefined correlation.

    Rank by descending absolute r, then CAN ID, byte offset, and field width.
    No physical interpretation or scale/offset estimation is performed.
    """
    validate_reference(reference_series)
    config = configuration(alignment, tolerance)
    pearson([], [], min_samples=min_samples)
    results = []
    for can_id in unique_ids(can_log):
        frames = frames_for_id(can_log, can_id)
        for candidate in byte_aligned_candidates(can_id):
            series = extract_candidate(frames, can_id, candidate)
            aligned = align_series(series, reference_series, config)
            xs, ys = [x for _, x, _ in aligned.rows], [y for _, _, y in aligned.rows]
            r = pearson(xs, ys, min_samples=min_samples)
            if r is not None:
                results.append(DiscoveryResult(can_id, candidate.byte_offset,
                                               candidate.width_bits, r, len(xs), candidate.endian, candidate.signed,
                                               alignment_diagnostics=aligned.diagnostics))
    return sorted(results, key=lambda r: (-abs(r.correlation), r.can_id, r.byte_offset, r.width_bits))
