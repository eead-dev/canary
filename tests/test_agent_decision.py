"""Models select evidence; deterministic values never require transcription."""

from copy import deepcopy
from dataclasses import asdict
import json
import unittest
from unittest.mock import patch

from canary.agent import DECISION_SCHEMA, checked_conclusion, validate
from canary.agent_evidence import EvidenceRegistry
from canary.llm.base import ModelResponse
from canary.llm.fake import FakeProvider
from tests import test_agent as fixtures


class DecisionProvider:
    def __init__(self, mutate=None):
        self.fake = FakeProvider()
        self.mutate = mutate
        self.decisions, self.evidence = [], []

    def respond(self, system, messages, tools, schema):
        assert schema == DECISION_SCHEMA
        if tools:
            return self.fake.respond(system, messages, tools, schema)
        self.evidence = messages[-1].content['allowed_evidence']
        selected = self.evidence[0]
        decision = {'candidate_ref': selected['candidate_ref'], 'signal_confidence': 'high',
                    'layout_confidence': 'low', 'layout_ambiguous': selected['layout_ambiguous'],
                    'alternative_refs': selected['distinct_alternative_refs'][:1],
                    'rationale': 'Strong reference tracking; this capture cannot distinguish equivalent layouts.'}
        if self.mutate:
            self.mutate(decision)
        self.decisions.append(deepcopy(decision))
        return ModelResponse(conclusion=decision)


class DecisionTests(unittest.TestCase):
    setUp = fixtures.AgentTests.setUp
    run_provider = fixtures.AgentTests.run_provider

    def test_large_equivalence_set_hydrated_without_model_transcription(self):
        provider = DecisionProvider()
        result = self.run_provider(provider)
        self.assertEqual(result.status, 'complete')
        conclusion = asdict(result.conclusion)
        decision = provider.decisions[0]
        analysis = next(e['output']['result'] for e in result.trace if e['name'] == 'analyze_candidate'
                        and e['output']['ok'] and e['output']['result']['candidate_ref'] == decision['candidate_ref'])
        keys = ('can_id', 'start_bit', 'width_bits', 'endian', 'signed')
        layout = lambda c: {k: c[k] for k in keys}
        self.assertEqual(conclusion['selected_candidate'], layout(analysis))
        self.assertEqual(conclusion['correlation'], analysis['correlation'])
        for k, v in analysis['fit'].items():
            self.assertEqual(conclusion[k], v)
        self.assertGreater(len(analysis['affine_equivalents']), 20)
        self.assertEqual(conclusion['affine_equivalent_layouts'], [layout(e['candidate']) for e in analysis['affine_equivalents']])
        group = analysis['equivalence']
        self.assertEqual(conclusion['equivalent_layouts'], [layout(e) for e in
            [group['representative'], *group['equivalent_candidates']] if layout(e) != layout(analysis)])
        self.assertNotIn('byte_offset', conclusion['selected_candidate'])
        self.assertEqual(checked_conclusion(conclusion, 'value', result.trace), result.conclusion)
        self.assertEqual(set(decision), set(DECISION_SCHEMA['properties']))
        for forbidden in ('scale', 'correlation', 'affine_equivalent_layouts', 'raw_to_raw'):
            self.assertNotIn(forbidden, json.dumps(decision))
        json.dumps(asdict(result), allow_nan=False)

    def test_stable_registry_refs_and_no_mutation(self):
        output = self.dispatcher.dispatch(fixtures.ToolCall('one', 'analyze_candidate', {
            'can_id': 291, 'byte_offset': 0, 'width_bits': 8, 'include_fit': True}))
        original = deepcopy(output)
        registry = EvidenceRegistry()
        a = registry.collect('analyze_candidate', output)
        b = registry.collect('analyze_candidate', output)
        self.assertEqual(a['result']['candidate_ref'], b['result']['candidate_ref'])
        self.assertEqual(output, original)
        self.assertEqual(len(registry.analyses), 1)

    def test_invalid_candidate_and_alternative_refs_repaired_boundedly(self):
        for mutation in (lambda d: d.update(candidate_ref='uncollected'),
                         lambda d: d.update(alternative_refs=['uncollected'])):
            result = self.run_provider(DecisionProvider(mutation))
            self.assertEqual(result.status, 'conclusion_validation_error')
            self.assertIn('must reference collected fitted', result.error['message'])
            self.assertEqual(sum(d['phase'] == 'finalization' for d in result.turn_trace), 3)

    def test_ambiguity_cannot_be_denied_or_overconfident(self):
        for mutation in (lambda d: d.update(layout_ambiguous=False),
                         lambda d: d.update(layout_confidence='high')):
            result = self.run_provider(DecisionProvider(mutation), max_finalization_attempts=1)
            self.assertEqual(result.status, 'conclusion_validation_error')
            self.assertIsNone(result.conclusion)

    def test_no_model_numeric_fields_allowed(self):
        provider = DecisionProvider(lambda d: d.update(scale=123))
        result = self.run_provider(provider, max_finalization_attempts=1)
        self.assertEqual(result.status, 'conclusion_validation_error')
        self.assertIn('unknown properties: scale', result.error['message'])

    def test_missing_evidence_is_internal_assembly_error(self):
        original = EvidenceRegistry.assemble

        def missing(registry, decision, name):
            registry.analyses[decision['candidate_ref']]['fit'].pop('scale')
            return original(registry, decision, name)

        provider = DecisionProvider()
        with patch.object(EvidenceRegistry, 'assemble', missing):
            result = self.run_provider(provider)
        self.assertEqual(result.status, 'evidence_assembly_error')
        self.assertEqual(len(provider.decisions), 1)
        self.assertIsNone(result.conclusion)

    def test_malformed_decision_corrects_with_semantic_schema(self):
        attempts = []

        def mutate(decision):
            attempts.append(1)
            if len(attempts) == 1:
                decision.pop('rationale')

        provider = DecisionProvider(mutate)
        result = self.run_provider(provider)
        self.assertEqual(result.status, 'complete')
        self.assertEqual(len(provider.decisions), 2)
        self.assertEqual(result.turn_trace[-2]['error']['message'], 'decision is missing required properties')
        validate(provider.decisions[-1], DECISION_SCHEMA)

    def test_search_references_match_analysis(self):
        result = self.run_provider(DecisionProvider())
        search = next(e['output']['result'] for e in result.trace if e['name'] == 'search_candidates')
        analysis = next(e['output']['result'] for e in result.trace if e['name'] == 'analyze_candidate' and e['output']['ok'])
        self.assertEqual(search['results'][0]['candidate_ref'], analysis['candidate_ref'])
