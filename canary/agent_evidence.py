"""Session references and lossless conclusion hydration from tool evidence."""

from copy import deepcopy
from .observation import CandidateSpec
from .llm.errors import provider_error


LAYOUT_KEYS = ('can_id', 'start_bit', 'width_bits', 'endian', 'signed')
METRICS = ('scale', 'offset', 'rmse', 'mae', 'r_squared')


class EvidenceAssemblyError(Exception):
    """Collected evidence is incomplete; model transcription cannot repair it."""


def layout(value):
    return {key: value[key] for key in LAYOUT_KEYS}


class EvidenceRegistry:
    def __init__(self):
        self.references = {}
        self.analyses = {}
        self.states = {}

    def selectable_refs(self):
        return [ref for ref in self.analyses if self.states.get(ref) == 'analyzed_fitted']

    def annotate(self, value):
        """Copy outputs; never mutate deterministic tool results or their cache."""
        if isinstance(value, list):
            return [self.annotate(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {}
        if all(key in value for key in LAYOUT_KEYS):
            canonical = CandidateSpec(value['start_bit'], value['width_bits'], value['endian'],
                                      value['signed'], value['can_id'])
            identity = (canonical.can_id, canonical.start_bit, canonical.width_bits, canonical.endian, canonical.signed)
            if identity not in self.references:
                self.references[identity] = f'cand_{len(self.references) + 1:04d}'
                self.states[self.references[identity]] = 'search_candidate'
            result['candidate_ref'] = self.references[identity]
        result.update({key: self.annotate(item) for key, item in value.items()})
        if 'candidate_ref' in result:
            ref = result['candidate_ref']
            result['evidence_state'] = self.states[ref]
            result['selectable'] = self.states[ref] == 'analyzed_fitted'
        return result

    def collect(self, name, output):
        if not output['ok']:
            return output
        result = self.annotate(output['result'])
        if name == 'analyze_candidate':
            ref = result['candidate_ref']
            if result.get('fit') is not None:
                self.states[ref] = 'analyzed_fitted'
                self.analyses[ref] = deepcopy(result)
            elif self.states[ref] != 'analyzed_fitted':
                self.states[ref] = 'analyzed_unfitted'
            # Refresh state annotations after promotion, including occurrences
            # of the same reference within equivalence evidence.
            result = self.annotate(result)
        return {**output, 'result': result}

    def summaries(self):
        def distinct_refs(a):
            group = a.get('equivalence', {})
            related = [layout(a), *[layout(c) for c in group.get('equivalent_candidates', [])],
                       *[layout(e['candidate']) for e in a.get('affine_equivalents', [])]]
            if group.get('representative'):
                related.append(layout(group['representative']))
            return [ref for ref, other in self.analyses.items() if layout(other) not in related]

        return [{'candidate_ref': ref, 'evidence_state': self.states[ref], 'selectable': True,
                 'candidate': layout(a),
                 'correlation': a.get('correlation'), 'fit': a.get('fit'),
                 'aligned_samples': a.get('aligned_samples'),
                 'layout_ambiguous': a.get('layout_ambiguous'),
                 'ambiguity_reason': a.get('ambiguity_reason'),
                 'exact_equivalent_count': len(a.get('equivalence', {}).get('equivalent_candidates', [])),
                 'affine_equivalent_count': len(a.get('affine_equivalents', [])),
                 'distinct_alternative_refs': distinct_refs(a)}
                for ref, a in self.analyses.items() if ref in self.selectable_refs()]

    def assemble(self, decision, reference_name):
        refs = [decision['candidate_ref'], *decision['alternative_refs']]
        allowed = self.selectable_refs()
        if any(ref not in allowed for ref in refs):
            invalid = [('candidate_ref' if i == 0 else 'alternative_ref') + ': ' +
                       provider_error(ValueError(ref))['message'] for i, ref in enumerate(refs) if ref not in allowed]
            raise ValueError('candidate_ref and alternative_refs must reference collected fitted analyses; '
                             'invalid ' + ', '.join(invalid) + '; selectable refs: ' + repr(allowed))
        if len(set(refs)) != len(refs):
            raise ValueError('selected and alternative references must be distinct')
        selected = self.analyses[refs[0]]
        try:
            group = selected['equivalence']
            exact = [layout(c) for c in [group['representative'], *group['equivalent_candidates']]
                     if layout(c) != layout(selected)]
            affine = [layout(e['candidate']) for e in selected['affine_equivalents']]
            alternatives = []
            for ref in refs[1:]:
                a = self.analyses[ref]
                alternatives.append({'candidate': layout(a), 'correlation': a['correlation'],
                                     **{k: a['fit'][k] for k in ('rmse', 'mae', 'r_squared')},
                                     'reason': 'Model-selected distinct comparison using collected fit evidence.'})
            result = {'reference_name': reference_name, 'selected_candidate': layout(selected),
                      'correlation': selected['correlation'], **{k: selected['fit'][k] for k in METRICS},
                      'confidence': decision['signal_confidence'],
                      **{k: decision[k] for k in ('signal_confidence', 'layout_confidence', 'layout_ambiguous', 'rationale')},
                      'equivalent_layouts': exact, 'affine_equivalent_layouts': affine,
                      'ambiguity_reason': selected['ambiguity_reason'], 'alternative_candidates': alternatives}
            if any(result[k] is None for k in ('correlation', *METRICS)):
                raise ValueError('missing metrics')
            return result
        except (KeyError, TypeError, ValueError) as exc:
            raise EvidenceAssemblyError('Collected analysis is incomplete; cannot assemble AgentConclusion') from exc
