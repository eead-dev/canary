"""Explicit, run-scoped decoding and evidence cache. No process-wide state."""

from array import array
from dataclasses import asdict, dataclass, replace
from math import gcd
from time import perf_counter

from .alignment import align_series, configuration
from .observation import CandidateSpec, decode_words, candidate_fields
from .reference import validate_reference


@dataclass(frozen=True)
class DecodedSeries:
    # Native integer bytes are an internal compact cache, never a file format.
    data: bytes
    minimum: int | None
    maximum: int | None

    @property
    def values(self):
        return memoryview(self.data).cast('i')

    @property
    def constant(self):
        return self.minimum is not None and self.minimum == self.maximum


@dataclass(frozen=True)
class EquivalenceClass:
    representative: CandidateSpec
    equivalent_candidates: list[CandidateSpec]
    equivalence_count: int
    evidence: str = "identical decoded time series on this aligned capture"


def layout_key(candidate):
    return (candidate.can_id, candidate.start_bit, candidate.width_bits,
            candidate.endian == 'big', candidate.signed)


class AnalysisRun:
    """Snapshot one capture/reference/configuration; discard after the analysis.

    Full decoded payload series are shared by inspection and aligned consumers.
    Aligned equivalence includes candidate timestamps and matched reference values,
    so scores are never reused across different observations. Byte-key equality
    checks the complete integer sequence; hash collisions cannot create a group.
    """

    def __init__(self, frames, reference, *, tolerance=0.0, alignment=None):
        self.started = perf_counter()
        validate_reference(reference)
        self.frames = tuple(frames)
        self.reference = tuple(tuple(pair) for pair in reference)
        self.config = configuration(alignment, tolerance)
        self.by_id = {}
        for frame in self.frames:
            self.by_id.setdefault(frame.can_id, []).append(frame)
        self._words, self._raw, self._aligned, self._axes = {}, {}, {}, {}
        self._axis_ids, self._axis_keys = {}, {}
        self._intern, self._groups, self._classes = {}, {}, {}
        self._scores, self._fits, self._ranked, self._prepared = {}, {}, {}, {}
        self._enumerated = set()
        self._affine_index = None
        self._affine_keys, self._relationships = {}, {}
        self.decoding_seconds = self.correlation_seconds = 0.0

    def check(self, frames, reference, tolerance, alignment):
        if (tuple(frames) != self.frames or tuple(tuple(p) for p in reference) != self.reference
                or configuration(alignment, tolerance) != self.config):
            raise ValueError("analysis run does not match capture, reference, or alignment configuration")

    def _pack(self, values):
        data = array('i', values).tobytes()
        if data not in self._intern:
            self._intern[data] = DecodedSeries(data, min(values) if len(values) else None,
                                              max(values) if len(values) else None)
        return self._intern[data]

    def decoded(self, candidate):
        if candidate.can_id not in self.by_id:
            raise ValueError("candidate CAN ID is not present in capture")
        if candidate in self._raw:
            return self._raw[candidate]
        # Signed decoding reuses the unsigned extraction. When the sign bit never
        # occurs, the entire series is identical, so no second extraction is needed.
        unsigned = replace(candidate, signed=False)
        if candidate.signed:
            base = self.decoded(unsigned)
            started = perf_counter()
            sign = 1 << (candidate.width_bits - 1)
            result = base if base.maximum is None or base.maximum < sign else self._pack(
                [v - 2*sign if v & sign else v for v in base.values])
        else:
            started = perf_counter()
            key = (candidate.can_id, candidate.endian)
            if key not in self._words:
                self._words[key] = [int.from_bytes(f.data, candidate.endian) for f in self.by_id[candidate.can_id]]
            result = self._pack(decode_words(self._words[key], candidate))
        self._raw[candidate] = result
        self.decoding_seconds += perf_counter() - started
        return result

    def axis(self, can_id):
        if can_id not in self._axes:
            rows = align_series([(f.timestamp, i) for i, f in enumerate(self.by_id[can_id])],
                                self.reference, self.config)
            indices = tuple(i for _, i, _ in rows.rows)
            times = tuple(t for t, _, _ in rows.rows)
            ys = tuple(y for _, _, y in rows.rows)
            self._axes[can_id] = (indices, times, ys, rows.diagnostics)
            self._axis_ids[can_id] = self._axis_keys.setdefault((times, ys), len(self._axis_keys))
        return self._axes[can_id]

    def aligned(self, candidate):
        if candidate not in self._aligned:
            raw = self.decoded(candidate)
            indices, _, _, _ = self.axis(candidate.can_id)
            started = perf_counter()
            values = raw.values
            self._aligned[candidate] = raw if indices == tuple(range(len(values))) else self._pack(
                [values[i] for i in indices])
            self.decoding_seconds += perf_counter() - started
        return self._aligned[candidate]

    def series_key(self, candidate):
        series = self.aligned(candidate)
        return (self._axis_ids[candidate.can_id], series.data)

    def enumerate(self):
        if self._enumerated:
            return
        for can_id in sorted(self.by_id):
            for candidate in candidate_fields(can_id):
                key = self.series_key(candidate)
                self._groups.setdefault(key, []).append(candidate)
                self._enumerated.add(candidate)
        for key, members in self._groups.items():
            members.sort(key=layout_key)
            group = EquivalenceClass(members[0], members[1:], len(members))
            for candidate in members:
                self._classes[candidate] = group

    def equivalence(self, candidate):
        self.enumerate()
        return self._classes[candidate]

    def _index_affine(self):
        # Integer difference vectors divided by their signed GCD are identical
        # iff nonconstant integer sequences are exactly affine-related. This is
        # a separate index: raw bytes, fits, scores and ranking are never merged.
        if self._affine_index is not None:
            return
        self.enumerate()
        self._affine_index = {}
        for key, members in self._groups.items():
            values = self.aligned(members[0]).values
            if len(values) < 3 or self.aligned(members[0]).constant:
                continue
            origin = values[0]
            divisor, direction = 0, 0
            for value in values:
                delta = value - origin
                divisor = gcd(divisor, delta)
                if not direction and delta:
                    direction = 1 if delta > 0 else -1
            divisor *= direction
            signature = (key[0], array('i', ((v-origin)//divisor for v in values)).tobytes())
            self._affine_keys[key] = signature
            self._affine_index.setdefault(signature, []).extend(members)
        for members in self._affine_index.values():
            members.sort(key=layout_key)

    def raw_relationship(self, candidate, other):
        """Compare other_raw = a*candidate_raw+b on identical aligned axes."""
        from .relationships import compare_raw_series
        first, second = self.series_key(candidate), self.series_key(other)
        if first[0] != second[0]:
            raise ValueError('raw comparison requires identical aligned timestamp axes')
        key = (first, second)
        if key not in self._relationships:
            self._relationships[key] = compare_raw_series(self.aligned(candidate).values,
                                                          self.aligned(other).values)
        return self._relationships[key]

    def ambiguity(self, candidate, alternatives=()):
        """All equivalent layouts; distinct alternatives limited to supplied scope.

        Different axes are not compared or resampled. The affine index covers
        every supported layout, regardless of the displayed top-N cutoff.
        """
        self._index_affine()
        key = self.series_key(candidate)
        exact = [c for c in self._groups[key] if c != candidate]
        affine = []
        for other in self._affine_index.get(self._affine_keys.get(key), []):
            if self.series_key(other) != key:
                evidence = self.raw_relationship(candidate, other)
                if evidence.relationship_type == 'affine':
                    affine.append({'candidate': asdict(other), **asdict(evidence)})
        related = {candidate, *exact, *(CandidateSpec(**e['candidate']) for e in affine)}
        distinct = []
        for other in dict.fromkeys(alternatives):
            if other in related:
                continue
            if self.series_key(other)[0] != key[0]:
                distinct.append({'candidate': asdict(other), 'relationship_type': 'uncompared',
                                 'reason': 'different aligned timestamp axes'})
            else:
                distinct.append({'candidate': asdict(other), **asdict(self.raw_relationship(candidate, other))})
        return {'exact_raw_equivalents': [asdict(c) for c in exact],
                'affine_equivalents': affine, 'distinct_alternatives': distinct,
                'distinct_alternatives_scope': 'supplied comparison candidates only; different axes remain uncompared',
                'layout_ambiguous': bool(exact or affine),
                'ambiguity_reason': 'affine_equivalent_layouts' if affine else
                                    'exact_raw_equivalent_layouts' if exact else 'none'}

    def correlation(self, candidate, min_samples=3):
        from .discovery import _prepare, _correlate
        if type(min_samples) is not int or min_samples < 3:
            raise ValueError("min_samples must be an integer of at least 3")
        key = (self.series_key(candidate), min_samples)
        if key not in self._scores:
            started = perf_counter()
            series = self.aligned(candidate)
            _, times, ys, _ = self.axis(candidate.can_id)
            score = None
            if len(series.values) >= min_samples and not series.constant:
                axis_key = self._axis_ids[candidate.can_id]
                if axis_key not in self._prepared:
                    self._prepared[axis_key] = _prepare(ys)
                score = _correlate(*_prepare(series.values), *self._prepared[axis_key])
            self._scores[key] = score
            self.correlation_seconds += perf_counter() - started
        return self._scores[key]

    def fit(self, candidate, min_samples=3):
        from .fitting import fit_linear
        if type(min_samples) is not int or min_samples < 3:
            raise ValueError("min_samples must be an integer of at least 3")
        key = (self.series_key(candidate), min_samples)
        if key not in self._fits:
            self._fits[key] = fit_linear(self.aligned(candidate).values, self.axis(candidate.can_id)[2],
                                         min_samples=min_samples)
        return self._fits[key]

    def rows(self, candidate):
        _, times, ys, _ = self.axis(candidate.can_id)
        return list(zip(times, self.aligned(candidate).values, ys))

    def statistics(self):
        return {"candidates_enumerated": len(self._enumerated),
                "unique_decoded_series": len(self._groups), "equivalence_classes": len(self._groups),
                "equivalent_candidates_grouped": len(self._enumerated) - len(self._groups),
                "constant_candidates_skipped": sum(self.aligned(c).constant for c in self._enumerated),
                "decoding_seconds": self.decoding_seconds, "correlation_seconds": self.correlation_seconds,
                "total_seconds": perf_counter() - self.started}


def analysis_run(frames, reference, tolerance=0.0, alignment=None, run=None):
    if run is None:
        return AnalysisRun(frames, reference, tolerance=tolerance, alignment=alignment)
    run.check(frames, reference, tolerance, alignment)
    return run
