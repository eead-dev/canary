"""Deterministic raw-field correlation against a supplied numeric series."""

from dataclasses import dataclass
import math

from .observation import Frame, candidate_fields, decode_words, frames_for_id, unique_ids
from .reference import Series, validate_reference
from .alignment import AlignmentDiagnostics, align_series, configuration
from .analysis import analysis_run, EquivalenceClass


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
    return _correlate(*_prepare(xs), *_prepare(ys))


def _prepare(values):
    """Original Pearson normalization, reusable for an unchanged reference."""
    magnitude = max(abs(v) for v in values)
    normalized = [v / magnitude for v in values] if magnitude else [0.0] * len(values)
    mean = math.fsum(normalized) / len(values)
    centered = [v - mean for v in normalized]
    return centered, math.fsum(v * v for v in centered)


def _correlate(dx, xx, dy, yy):
    if xx == 0 or yy == 0:
        return None
    r = math.fsum(x * y for x, y in zip(dx, dy)) / math.sqrt(xx) / math.sqrt(yy)
    return max(-1.0, min(1.0, r))


@dataclass(frozen=True)
class DiscoveryResult:
    can_id: int
    byte_offset: int | None
    width_bits: int
    correlation: float
    aligned_samples: int
    endian: str = "little"
    signed: bool = False
    alignment_diagnostics: AlignmentDiagnostics | None = None
    start_bit: int | None = None
    equivalence: EquivalenceClass | None = None

    def __post_init__(self):
        if self.start_bit is None:
            object.__setattr__(self, "start_bit", self.byte_offset * 8)


def discover_signal(can_log: list[Frame], reference_series: Series, *,
                    tolerance: float = 0.0, min_samples: int = 3, alignment: str | None = None,
                    run=None) -> list[DiscoveryResult]:
    """Keep every rankable layout in the original order; expose exact equivalence."""
    pearson([], [], min_samples=min_samples)
    run = analysis_run(can_log, reference_series, tolerance, alignment, run)
    if min_samples in run._ranked:
        return list(run._ranked[min_samples])
    run.enumerate()
    results = []
    for can_id in sorted(run.by_id):
        for candidate in candidate_fields(can_id):
            r = run.correlation(candidate, min_samples)
            if r is not None:
                results.append(DiscoveryResult(can_id, candidate.byte_offset,
                    candidate.width_bits, r, len(run.aligned(candidate).values), candidate.endian, candidate.signed,
                    alignment_diagnostics=run.axis(can_id)[3], start_bit=candidate.start_bit,
                    equivalence=run.equivalence(candidate)))
    ranked = sorted(results, key=lambda r: (-abs(r.correlation), r.can_id, r.start_bit, r.width_bits))
    run._ranked[min_samples] = tuple(ranked)
    return ranked
