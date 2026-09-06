"""Regression for attempted conclusions that previously stayed in exploration."""

from dataclasses import asdict
import json
import unittest
from unittest.mock import patch

from canary.agent import CONCLUSION_SCHEMA, DECISION_SCHEMA, FINALIZATION, validate
from canary.llm.base import ModelResponse, ToolCall
from canary.llm.fake import FakeProvider
from tests import test_agent as fixtures


class RepairProvider:
    def __init__(self, *, plain=False, exhaust=False):
        self.calls = 0
        self.plain, self.exhaust = plain, exhaust
        self.fake = FakeProvider()
        self.requests = []

    def respond(self, system, messages, tools, schema):
        self.calls += 1
        self.requests.append((list(messages), tools))
        if self.calls <= 3:
            name = ('summarize_capture', 'list_can_ids', 'search_candidates')[self.calls - 1]
            return ModelResponse(tool_calls=[ToolCall(str(self.calls), name, {})])
        if self.calls == 4:
            return self.fake.respond(system, messages, tools, schema)
        if self.calls == 5 or self.exhaust:
            return ModelResponse(text='{}') if self.plain else ModelResponse(conclusion={'unexpected': True})
        return self.fake.respond(system, messages, tools, schema)


class RepairTests(unittest.TestCase):
    setUp = fixtures.AgentTests.setUp
    run_provider = fixtures.AgentTests.run_provider

    def run_repair(self, provider):
        # Isolate the reactive path: it must work even if the proactive gate
        # has not fired, as in the observed real capture.
        with patch('canary.agent.ready_to_finalize', return_value=False):
            return self.run_provider(provider, max_turns=5)

    def test_observed_fifth_turn_transitions_and_corrects(self):
        provider = RepairProvider()
        result = self.run_repair(provider)
        self.assertEqual(result.status, 'complete')
        self.assertEqual(result.turns, 6)
        self.assertEqual([d['response_kind'] for d in result.turn_trace[:4]], ['tool_calls'] * 4)
        self.assertEqual(result.turn_trace[4]['response_kind'], 'final_candidate')
        self.assertEqual(result.turn_trace[4]['transition'], 'reactive_finalization')
        self.assertTrue(all(d['phase'] == 'finalization' for d in result.turn_trace[5:]))
        self.assertTrue(all(tools == [] for _, tools in provider.requests[5:]))
        feedback = provider.requests[5][0][-1].content
        self.assertEqual(feedback['expected_schema']['required'], DECISION_SCHEMA['required'])
        self.assertIn('enum', feedback['expected_schema']['properties']['candidate_ref'])
        self.assertTrue(feedback['instruction'].startswith(FINALIZATION))
        self.assertIn('unknown properties: unexpected', feedback['error']['message'])
        self.assertEqual(len(result.trace), 6)
        json.dumps(asdict(result), allow_nan=False)

    def test_plain_json_attempt_transitions(self):
        result = self.run_repair(RepairProvider(plain=True))
        self.assertEqual(result.status, 'complete')
        self.assertEqual(result.turn_trace[4]['response_kind'], 'plain_text')
        self.assertEqual(result.turn_trace[4]['transition'], 'reactive_finalization')
        self.assertEqual(result.turn_trace[5]['phase'], 'finalization')

    def test_three_repairs_exhaust_separate_budget(self):
        provider = RepairProvider(exhaust=True)
        result = self.run_repair(provider)
        self.assertEqual(result.status, 'conclusion_validation_error')
        self.assertEqual(result.turns, 8)
        self.assertEqual([d['phase'] for d in result.turn_trace[5:]], ['finalization'] * 3)
        self.assertTrue(all(tools == [] for _, tools in provider.requests[5:]))
        for messages, _ in provider.requests[5:]:
            self.assertEqual(messages[-1].content['expected_schema']['required'], DECISION_SCHEMA['required'])
            self.assertIn('enum', messages[-1].content['expected_schema']['properties']['candidate_ref'])
        self.assertIsNone(result.conclusion)

    def test_nested_unknown_field_rejected_and_named(self):
        result = self.run_provider(FakeProvider())
        data = asdict(result.conclusion)
        self.assertTrue(data['affine_equivalent_layouts'])
        data['affine_equivalent_layouts'][0]['raw_scale'] = 4
        with self.assertRaisesRegex(ValueError, r'conclusion.affine_equivalent_layouts\[0\] has unknown properties: raw_scale'):
            validate(data, CONCLUSION_SCHEMA, 'conclusion')
        with patch.dict('os.environ', {'PRIVATE_TEST_VALUE': 'private-field-name'}):
            data['affine_equivalent_layouts'][0]['private-field-name'] = 1
            try:
                validate(data, CONCLUSION_SCHEMA, 'conclusion')
            except ValueError as exc:
                self.assertNotIn('private-field-name', str(exc))

    def test_non_json_text_does_not_trigger_reactive_mode(self):
        result = self.run_provider(fixtures.ScriptProvider([ModelResponse(text='not JSON')] * 2), max_turns=2)
        self.assertEqual(result.status, 'max_turns')
        self.assertTrue(all(d['phase'] == 'exploration' for d in result.turn_trace))
