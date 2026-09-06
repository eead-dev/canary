"""Offline termination guards; conclusions still pass the existing validator."""

from dataclasses import asdict
import json
import unittest
from unittest.mock import Mock

from canary.agent import SYSTEM
from canary.llm.base import ModelResponse, ToolCall
from canary.llm.fake import FakeProvider
from tests import test_agent as fixtures


class TerminationTests(unittest.TestCase):
    setUp = fixtures.AgentTests.setUp
    run_provider = fixtures.AgentTests.run_provider

    def analyze(self, identity, **options):
        locator = {} if 'start_bit' in options else {'byte_offset': 0}
        return self.dispatcher.dispatch(ToolCall(identity, 'analyze_candidate', {
            'can_id': 291, 'width_bits': 8, **locator, **options}))

    def test_identical_and_canonical_arguments_reuse_evidence(self):
        original = self.dispatcher.functions['analyze_candidate']
        spy = Mock(wraps=original)
        self.dispatcher.functions['analyze_candidate'] = spy
        self.assertTrue(self.analyze('first', include_fit=True)['ok'])
        for identity, options in [('repeat', {}), ('canonical', {
                'start_bit': 0, 'endian': 'little', 'signed': False,
                'tolerance': 0.02, 'min_samples': 300})]:
            result = self.analyze(identity, include_fit=True, **options)
            self.assertEqual(result['error']['code'], 'evidence_already_exists')
            self.assertEqual(result['error']['original_call_id'], 'first')
        self.assertEqual(spy.call_count, 1)
        json.dumps(result, allow_nan=False)

    def test_fit_upgrade_and_validation_are_preserved(self):
        self.assertTrue(self.analyze('raw')['ok'])
        self.assertTrue(self.analyze('fit', include_fit=True)['ok'])
        self.assertEqual(self.analyze('invalid', start_bit=57)['error']['code'], 'invalid_arguments')
        self.assertEqual(self.analyze('invalid-type', signed=1)['error']['code'], 'invalid_arguments')

    def test_equivalent_layouts_do_not_need_exhaustive_analysis(self):
        evidence = self.analyze('first', include_fit=True)['result']
        groups = [('exact', evidence['equivalence']['equivalent_candidates']),
                  ('affine', [e['candidate'] for e in evidence['affine_equivalents']])]
        spy = Mock(wraps=self.dispatcher.functions['analyze_candidate'])
        self.dispatcher.functions['analyze_candidate'] = spy
        for relationship, members in groups:
            self.assertTrue(members)
            member = members[0]
            arguments = {k: member[k] for k in ('can_id', 'start_bit', 'width_bits', 'endian', 'signed')}
            result = self.dispatcher.dispatch(ToolCall(relationship, 'analyze_candidate', {
                **arguments, 'include_fit': True}))
            self.assertEqual(result['error']['relationship'], relationship)
            self.assertEqual(result['error']['original_call_id'], 'first')
        spy.assert_not_called()

    def test_ambiguous_conclusion_after_redundant_attempt(self):
        fake = FakeProvider()

        class RepeatingProvider:
            attempted = False

            def respond(self, system, messages, tools, schema):
                analyses = [m.content for m in messages if m.role == 'tool'
                            and m.content['name'] == 'analyze_candidate' and m.content['output']['ok']]
                if analyses and not self.attempted:
                    self.attempted = True
                    return ModelResponse(tool_calls=[ToolCall('redundant', 'analyze_candidate',
                                                              analyses[0]['arguments'])])
                return fake.respond(system, messages, tools, schema)

        result = self.run_provider(RepeatingProvider())
        self.assertEqual(result.status, 'complete')
        self.assertLess(result.turns, 12)
        self.assertTrue(result.conclusion.layout_ambiguous)
        self.assertEqual(result.conclusion.signal_confidence, 'high')
        self.assertEqual(result.conclusion.layout_confidence, 'low')
        self.assertEqual(result.trace[-1]['output']['error']['code'], 'evidence_already_exists')
        json.dumps(asdict(result), allow_nan=False)

    def test_guidance_explicitly_accepts_ambiguity(self):
        self.assertIn('A valid ambiguous conclusion is a successful outcome.', SYSTEM)
        self.assertIn('Do not repeatedly analyze candidates', SYSTEM)
        self.assertIn('non-equivalent alternative comparison', SYSTEM)
