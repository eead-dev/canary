"""Deterministic timestamp alignment with one-to-one chronological matches."""

from bisect import bisect_left
from dataclasses import dataclass
import math

from .reference import Series, validate_reference


@dataclass(frozen=True)
class AlignmentConfig:
    mode: str = "exact"
    tolerance: float = 0.0

    def __post_init__(self):
        if self.mode not in ("exact", "nearest"):
            raise ValueError("alignment must be exact or nearest")
        if type(self.tolerance) not in (int, float) or not math.isfinite(self.tolerance) or self.tolerance < 0:
            raise ValueError("timestamp tolerance must be finite and nonnegative")


def configuration(mode: str | None, tolerance: float) -> AlignmentConfig:
    """Preserve legacy nonzero-tolerance callers; explicit exact always means equality."""
    config = AlignmentConfig("exact" if mode is None else mode, tolerance)
    return AlignmentConfig("nearest", tolerance) if mode is None and tolerance > 0 else config


@dataclass(frozen=True)
class AlignmentDiagnostics:
    candidate_sample_count: int
    matched_sample_count: int
    unmatched_sample_count: int
    match_ratio: float
    mean_absolute_timestamp_error: float | None
    max_absolute_timestamp_error: float | None


@dataclass(frozen=True)
class AlignmentResult:
    # Rows use candidate timestamp, candidate value, matched reference value.
    rows: list[tuple[float, float, float]]
    diagnostics: AlignmentDiagnostics


def align_series(candidate: Series, reference: Series,
                 config: AlignmentConfig = AlignmentConfig()) -> AlignmentResult:
    validate_reference(reference)
    if any(not math.isfinite(t) or not math.isfinite(v) for t, v in candidate):
        raise ValueError("candidate timestamps and values must be finite")
    times = [t for t, _ in reference]
    left, rows, errors = 0, [], []
    tolerance = config.tolerance if config.mode == "nearest" else 0.0
    for timestamp, value in sorted(candidate, key=lambda pair: pair[0]):
        if not times or timestamp < times[0] or timestamp > times[-1]:
            continue
        index = bisect_left(times, timestamp, lo=left)
        options = [i for i in (index - 1, index) if left <= i < len(times)]
        if not options:
            continue
        match = min(options, key=lambda i: (abs(times[i] - timestamp), times[i]))
        error = abs(times[match] - timestamp)
        if error <= tolerance:
            rows.append((timestamp, value, reference[match][1]))
            errors.append(error)
            left = match + 1
    count, matched = len(candidate), len(rows)
    return AlignmentResult(rows, AlignmentDiagnostics(count, matched, count - matched,
        matched / count if count else 0.0, math.fsum(errors) / matched if matched else None,
        max(errors) if errors else None))
