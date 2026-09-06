"""Only canonical fitted references can be selected for conclusion hydration."""

from dataclasses import asdict
from copy import deepcopy
import unittest

from canary.agent import checked_conclusion
from canary.agent_evidence import EvidenceRegistry
from canary.llm.base import ModelResponse, ToolCall
from tests import test_agent as fixtures
from tests.test_agent_decision import DecisionProvider


class EarlyDecisionProvider(DecisionProvider):
    def __init__(self):
        super().__init__()
        self.calls = 0
        self.prompts = []

    def respond(self, system, messages, tools, schema):
        self.calls += 1
        self.prompts.append((list(messages), tools))
        if self.calls == 1:
            return ModelResponse(tool_calls=[ToolCall('search', 'search_candidates', {})])
        if self.calls == 2:
            search = messages[-1].content['output']['result']
            self.early_ref = search['results'][0]['candidate_ref']
            return ModelResponse(conclusion={'candidate_ref': self.early_ref,
                'signal_confidence': 'high', 'layout_confidence': 'low', 'layout_ambiguous': True,
                'alternative_refs': [], 'rationale': 'Attempt before fitted evidence.'})
        return super().respond(system, messages, tools, schema)


class SelectableTests(unittest.TestCase):
    setUp = fixtures.AgentTests.setUp
    run_provider = fixtures.AgentTests.run_provider

    def test_live_regression_search_then_early_decision_then_fit(self):
        provider = EarlyDecisionProvider()
        result = self.run_provider(provider)
        self.assertEqual(result.status, 'complete')
        self.assertEqual([e['phase'] for e in result.turn_trace],
                         ['exploration', 'exploration', 'exploration', 'finalization'])
        self.assertEqual(result.turn_trace[1]['transition'], 'awaiting_fitted_evidence')
        feedback = provider.prompts[2][0][-1].content
        self.assertEqual(feedback['code'], 'no_selectable_evidence')
        self.assertEqual(feedback['selectable_candidate_refs'], [])
        self.assertTrue(provider.prompts[2][1])
        final = provider.prompts[-1][0][-1].content
        self.assertEqual(final['selectable_candidate_refs'], [e['candidate_ref'] for e in final['allowed_evidence']])
        self.assertIn(provider.early_ref, final['selectable_candidate_refs'])
        self.assertEqual(provider.decisions[-1]['candidate_ref'], provider.early_ref)
        self.assertEqual(checked_conclusion(asdict(result.conclusion), 'value', result.trace), result.conclusion)

    def evidence(self):
        return self.dispatcher.dispatch(ToolCall('fit', 'analyze_candidate', {
            'can_id': 291, 'byte_offset': 0, 'width_bits': 8, 'include_fit': True}))

    def test_stable_promotion_and_unfitted_search_rejection(self):
        registry = EvidenceRegistry()
        fitted = self.evidence()
        search = {'ok': True, 'result': {k: fitted['result'][k] for k in
                  ('can_id', 'start_bit', 'width_bits', 'endian', 'signed')}}
        first = registry.collect('search_candidates', search)['result']
        ref = first['candidate_ref']
        self.assertEqual(first['evidence_state'], 'search_candidate')
        decision = {'candidate_ref': ref, 'alternative_refs': []}
        with self.assertRaisesRegex(ValueError, 'invalid candidate_ref'):
            registry.assemble(decision, 'value')
        unfitted = deepcopy(fitted)
        unfitted['result'].pop('fit')
        second = registry.collect('analyze_candidate', unfitted)['result']
        self.assertEqual(second['candidate_ref'], ref)
        self.assertEqual(second['evidence_state'], 'analyzed_unfitted')
        self.assertEqual(registry.selectable_refs(), [])
        with self.assertRaises(ValueError):
            registry.assemble(decision, 'value')
        third = registry.collect('analyze_candidate', fitted)['result']
        self.assertEqual(third['candidate_ref'], ref)
        self.assertEqual(third['evidence_state'], 'analyzed_fitted')
        self.assertTrue(third['selectable'])
        self.assertEqual(registry.selectable_refs(), [ref])
        registry.collect('analyze_candidate', unfitted)
        registry.collect('analyze_candidate', fitted)
        self.assertEqual(registry.selectable_refs(), [ref])

    def test_unfitted_and_stale_alternatives_rejected_with_allowlist(self):
        registry = EvidenceRegistry()
        fit = registry.collect('analyze_candidate', self.evidence())['result']
        other = {**fit, 'start_bit': 8}
        other.pop('candidate_ref')
        other.pop('fit')
        unfit = registry.collect('analyze_candidate', {'ok': True, 'result': other})['result']
        for ref in (unfit['candidate_ref'], 'stale_ref', fit['candidate_ref']):
            with self.assertRaises(ValueError) as error:
                registry.assemble({'candidate_ref': fit['candidate_ref'], 'alternative_refs': [ref]}, 'value')
            if ref != fit['candidate_ref']:
                self.assertIn('selectable refs:', str(error.exception))
                self.assertIn(fit['candidate_ref'], str(error.exception))

    def test_repair_prompt_only_lists_fitted_refs(self):
        class InvalidProvider(DecisionProvider):
            def respond(self, system, messages, tools, schema):
                if not tools:
                    prompt = messages[-1].content
                    assert prompt['selectable_candidate_refs'] == [e['candidate_ref'] for e in prompt['allowed_evidence']]
                return super().respond(system, messages, tools, schema)
        provider = InvalidProvider(lambda d: d.update(candidate_ref='stale_ref'))
        result = self.run_provider(provider)
        self.assertEqual(result.status, 'conclusion_validation_error')
        self.assertIn('selectable refs:', result.error['message'])

    def test_equivalent_eight_bit_endian_has_one_reference(self):
        registry = EvidenceRegistry()
        value = {'can_id': 291, 'start_bit': 0, 'width_bits': 8, 'signed': False, 'endian': 'little'}
        first = registry.annotate(value)
        second = registry.annotate({**value, 'endian': 'big'})
        self.assertEqual(first['candidate_ref'], second['candidate_ref'])
        self.assertEqual(len(registry.references), 1)
