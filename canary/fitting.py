"""Ordinary least squares and reconstruction of aligned raw observations."""

import csv
from dataclasses import dataclass
import math
from pathlib import Path

from .discovery import DiscoveryResult, align_observations, discover_signal
from .observation import CandidateSpec, Frame, extract_candidate
from .reference import Series
from .analysis import analysis_run, EquivalenceClass
from .alignment import AlignmentDiagnostics, align_series, configuration


def _validate_pairs(xs: list[float], ys: list[float]) -> None:
    if len(xs) != len(ys):
        raise ValueError("inputs must have equal lengths")
    if any(not math.isfinite(v) for values in (xs, ys) for v in values):
        raise ValueError("inputs must be finite")


@dataclass(frozen=True)
class Metrics:
    rmse: float
    mae: float
    r_squared: float | None


@dataclass(frozen=True)
class LinearFit:
    scale: float
    offset: float
    rmse: float
    mae: float
    r_squared: float | None


def reconstruct(raw: list[float], scale: float, offset: float) -> list[float]:
    if any(not math.isfinite(v) for v in [scale, offset, *raw]):
        raise ValueError("reconstruction inputs must be finite")
    values = [x * scale + offset for x in raw]
    if any(not math.isfinite(v) for v in values):
        raise ValueError("reconstruction exceeds finite numeric range")
    return values


def reconstruction_metrics(reference: list[float], reconstructed: list[float]) -> Metrics:
    _validate_pairs(reference, reconstructed)
    if not reference:
        raise ValueError("metrics require at least one sample")
    try:
        residuals = [y - p for y, p in zip(reference, reconstructed)]
        sse = math.fsum(e * e for e in residuals)
        mean = math.fsum(y / len(reference) for y in reference)
        sst = math.fsum((y - mean) ** 2 for y in reference)
        rmse = math.sqrt(sse / len(reference))
        mae = math.fsum(abs(e) / len(reference) for e in residuals)
        r_squared = None if sst == 0 else 1 - sse / sst
        if any(not math.isfinite(v) for v in (rmse, mae, sst)) or (
                r_squared is not None and not math.isfinite(r_squared)):
            raise ValueError("metrics exceed finite numeric range")
    except OverflowError as exc:
        raise ValueError("metrics exceed finite numeric range") from exc
    return Metrics(rmse, mae, r_squared)


def fit_linear(xs: list[float], ys: list[float], *, min_samples: int = 3) -> LinearFit | None:
    """Fit y = scale*x + offset; None for insufficient or constant raw data."""
    _validate_pairs(xs, ys)
    if type(min_samples) is not int or min_samples < 3:
        raise ValueError("min_samples must be an integer of at least 3")
    if len(xs) < min_samples or min(xs) == max(xs):
        return None
    try:
        mean_x = math.fsum(x / len(xs) for x in xs)
        mean_y = math.fsum(y / len(ys) for y in ys)
        dx, dy = [x - mean_x for x in xs], [y - mean_y for y in ys]
        denominator = math.fsum(x * x for x in dx)
        if denominator == 0:
            return None
        scale = math.fsum(x * y for x, y in zip(dx, dy)) / denominator
        offset = mean_y - scale * mean_x
        predictions = reconstruct(xs, scale, offset)
        metrics = reconstruction_metrics(ys, predictions)
    except OverflowError as exc:
        raise ValueError("fit exceeds finite numeric range") from exc
    return LinearFit(scale, offset, metrics.rmse, metrics.mae, metrics.r_squared)


@dataclass(frozen=True)
class FittedResult:
    can_id: int
    byte_offset: int | None
    width_bits: int
    endian: str
    signed: bool
    correlation: float
    scale: float
    offset: float
    rmse: float
    mae: float
    r_squared: float | None
    aligned_samples: int
    alignment_diagnostics: AlignmentDiagnostics | None = None
    start_bit: int | None = None
    equivalence: EquivalenceClass | None = None

    def __post_init__(self):
        if self.start_bit is None:
            object.__setattr__(self, "start_bit", self.byte_offset * 8)


def fit_ranked(can_log: list[Frame], reference_series: Series,
               ranked: list[DiscoveryResult], *, tolerance: float = 0.0,
               min_samples: int = 3, alignment: str | None = None, run=None) -> list[FittedResult]:
    run = analysis_run(can_log, reference_series, tolerance, alignment, run)
    results = []
    for result in ranked:
        candidate = CandidateSpec(result.start_bit, result.width_bits, result.endian, result.signed, result.can_id)
        rows = run.rows(candidate)
        diagnostics = run.axis(result.can_id)[3]
        fit = run.fit(candidate, min_samples)
        if fit is not None:
            results.append(FittedResult(result.can_id, result.byte_offset, result.width_bits,
                                        result.endian, result.signed, result.correlation,
                                        fit.scale, fit.offset, fit.rmse, fit.mae, fit.r_squared, len(rows), diagnostics, result.start_bit, result.equivalence))
    return results


def discover_and_fit(can_log: list[Frame], reference_series: Series, top_n: int = 10, *,
                     tolerance: float = 0.0, min_samples: int = 3, alignment: str | None = None, run=None) -> list[FittedResult]:
    if type(top_n) is not int or top_n < 1:
        raise ValueError("top_n must be a positive integer")
    run = analysis_run(can_log, reference_series, tolerance, alignment, run)
    ranked = discover_signal(can_log, reference_series, tolerance=tolerance, min_samples=min_samples, alignment=alignment, run=run)
    return fit_ranked(can_log, reference_series, ranked[:top_n],
                      tolerance=tolerance, min_samples=min_samples, alignment=alignment, run=run)


def write_reconstruction(path: str | Path, can_log: list[Frame], reference_series: Series,
                         result: FittedResult, *, tolerance: float = 0.0, alignment: str | None = None, run=None) -> None:
    """Write matched samples with candidate timestamps; overwrite the output."""
    run = analysis_run(can_log, reference_series, tolerance, alignment, run)
    rows = run.rows(CandidateSpec(result.start_bit, result.width_bits, result.endian, result.signed, result.can_id))
    predictions = reconstruct([x for _, x, _ in rows], result.scale, result.offset)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("timestamp", "reference", "reconstructed", "raw"))
        for (timestamp, raw_value, reference), prediction in zip(rows, predictions):
            writer.writerow((timestamp, reference, prediction, raw_value))
