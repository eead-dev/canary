"""Raw-to-raw evidence, independent of reference fitting and ranking."""

from dataclasses import dataclass
import math


RESIDUAL_TOLERANCE = 1e-8
AFFINE_EXPLANATION = (
    "These layouts produce different raw values but are related by an exact affine "
    "transformation on this capture. The external reference therefore cannot "
    "distinguish their physical reconstruction after scale/offset fitting."
)


@dataclass(frozen=True)
class RawRelationship:
    relationship_type: str
    scale_between_raw: float | None
    offset_between_raw: float | None
    rmse_between_raw: float | None
    max_abs_residual: float | None
    sample_count: int
    reason: str


def compare_raw_series(x, y):
    """Fit y = a*x+b. Every residual must be <= 1e-8 raw units.

    This absolute tolerance is far below one integer raw unit in the supported
    field domain. It admits floating-point roundoff, not quantization noise or
    outliers. At least three observations and two nonconstant series are needed;
    constants cannot establish an invertible information-preserving relationship.
    """
    from .fitting import fit_linear
    if len(x) != len(y):
        raise ValueError("raw series must have equal lengths on the same aligned axis")
    if any(not math.isfinite(v) for series in (x, y) for v in series):
        raise ValueError("raw series must contain only finite values")
    n = len(x)
    if n < 3 or min(x) == max(x) or min(y) == max(y):
        return RawRelationship('distinct', None, None, None, None, n,
                               'insufficient samples' if n < 3 else 'constant series')
    if all(a == b for a, b in zip(x, y)):
        return RawRelationship('exact', 1.0, 0.0, 0.0, 0.0, n, 'identical raw values')
    fit = fit_linear(x, y)
    if fit is None:
        return RawRelationship('distinct', None, None, None, None, n, 'degenerate fit')
    maximum = max(abs(b - (fit.scale*a + fit.offset)) for a, b in zip(x, y))
    equivalent = fit.scale != 0 and maximum <= RESIDUAL_TOLERANCE
    return RawRelationship('affine' if equivalent else 'distinct', fit.scale,
                           fit.offset, fit.rmse, maximum, n,
                           'every residual within 1e-8 raw units' if equivalent else 'nonzero residual beyond tolerance')
