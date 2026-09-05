"""Deterministic raw-field correlation against a supplied numeric series."""

from bisect import bisect_left
from dataclasses import dataclass
import math

from .observation import Frame, byte_aligned_candidates, extract_candidate, frames_for_id, unique_ids
from .reference import Series, validate_reference


def align_samples(candidate: Series, reference: Series, *, tolerance: float = 0.0
                  ) -> tuple[list[float], list[float]]:
    """Greedy nearest matching in time order, without reuse or interpolation.

    Ties prefer the earlier reference timestamp. Matches are monotonic; skipped
    reference samples cannot be reused later. Duplicate candidate timestamps
    retain input order. Tolerance is an inclusive distance in seconds.
    """
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("tolerance must be finite and nonnegative")
    validate_reference(reference)
    if any(not math.isfinite(t) or not math.isfinite(v) for t, v in candidate):
        raise ValueError("candidate timestamps and values must be finite")
    times = [t for t, _ in reference]
    left = 0
    xs, ys = [], []
    for timestamp, value in sorted(candidate, key=lambda pair: pair[0]):
        index = bisect_left(times, timestamp, lo=left)
        options = [i for i in (index - 1, index) if left <= i < len(times)]
        if not options:
            continue
        match = min(options, key=lambda i: (abs(times[i] - timestamp), times[i]))
        if abs(times[match] - timestamp) <= tolerance:
            xs.append(value)
            ys.append(reference[match][1])
            left = match + 1
    return xs, ys


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


def discover_signal(can_log: list[Frame], reference_series: Series, *,
                    tolerance: float = 0.0, min_samples: int = 3) -> list[DiscoveryResult]:
    """Search every supported field; omit candidates with undefined correlation.

    Rank by descending absolute r, then CAN ID, byte offset, and field width.
    No physical interpretation or scale/offset estimation is performed.
    """
    validate_reference(reference_series)
    align_samples([], reference_series, tolerance=tolerance)
    pearson([], [], min_samples=min_samples)
    results = []
    for can_id in unique_ids(can_log):
        frames = frames_for_id(can_log, can_id)
        for candidate in byte_aligned_candidates():
            series = extract_candidate(frames, can_id, candidate)
            xs, ys = align_samples(series, reference_series, tolerance=tolerance)
            r = pearson(xs, ys, min_samples=min_samples)
            if r is not None:
                results.append(DiscoveryResult(can_id, candidate.byte_offset,
                                               candidate.width_bits, r, len(xs)))
    return sorted(results, key=lambda r: (-abs(r.correlation), r.can_id, r.byte_offset, r.width_bits))
