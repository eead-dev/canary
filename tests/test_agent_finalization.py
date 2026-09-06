"""Forced finalization and metadata-only diagnostics, without live providers."""

from dataclasses import asdict
import json
import unittest
from unittest.mock import patch

from canary.agent import FINALIZATION, CONCLUSION_SCHEMA
from canary.llm.base import ModelResponse, ToolCall
from canary.llm.fake import FakeProvider
from tests import test_agent as fixtures
from tests import test_openrouter as wire_fixtures


class FinalizingProvider:
    def __init__(self, failures=(), text=False):
        self.fake = FakeProvider()
        self.failures = iter(failures)
        self.text = text
        self.final_calls = []

    def respond(self, system, messages, tools, schema):
        if FINALIZATION in system:
            assert tools == []
            self.final_calls.append(list(messages))
            failed = next(self.failures, None)
            if failed is not None:
                return failed
            result = self.fake.respond(system, messages, tools, schema)
            return ModelResponse(text=json.dumps(result.conclusion)) if self.text else result
        return self.fake.respond(system, messages, tools, schema)


class FinalizationTests(unittest.TestCase):
    setUp = fixtures.AgentTests.setUp
    run_provider = fixtures.AgentTests.run_provider

    def test_forced_finalization_has_separate_budget_and_no_tools(self):
        provider = FinalizingProvider()
        result = self.run_provider(provider, max_turns=2)
        self.assertEqual(result.status, 'complete')
        self.assertEqual(result.turns, 3)
        self.assertEqual(len(provider.final_calls), 1)
        self.assertEqual([e['phase'] for e in result.turn_trace],
                         ['exploration', 'exploration', 'finalization'])
        self.assertEqual(result.turn_trace[-1]['validation'], 'passed')
        json.dumps(asdict(result), allow_nan=False)

    def test_validation_feedback_then_corrected_conclusion(self):
        provider = FinalizingProvider([ModelResponse(conclusion={})])
        result = self.run_provider(provider)
        self.assertEqual(result.status, 'complete')
        self.assertEqual(result.turn_trace[-2]['error']['message'], 'decision is missing required properties')
        feedback = provider.final_calls[-1][-1].content
        self.assertEqual(feedback['instruction'], FINALIZATION)
        self.assertEqual(feedback['error']['message'], 'decision is missing required properties')

    def test_finalization_exhaustion(self):
        result = self.run_provider(FinalizingProvider([ModelResponse(conclusion={})] * 3))
        self.assertEqual(result.status, 'conclusion_validation_error')
        self.assertIsNone(result.conclusion)
        self.assertEqual(result.turns, 5)
        self.assertEqual(result.error['message'], 'decision is missing required properties')

    def test_plain_text_complete_json_and_no_fuzzy_parsing(self):
        result = self.run_provider(FinalizingProvider(text=True))
        self.assertEqual(result.status, 'complete')
        self.assertEqual(result.turn_trace[-1]['response_kind'], 'plain_text')
        self.assertTrue(result.turn_trace[-1]['conclusion_parsing_attempted'])
        result = self.run_provider(FinalizingProvider([ModelResponse(text='Here is JSON: {}')]),
                                   max_finalization_attempts=1)
        self.assertEqual(result.status, 'conclusion_validation_error')

    def test_empty_and_exploration_requests_cannot_escape_finalization(self):
        for response, kind in [(ModelResponse(), 'empty'),
                               (ModelResponse(tool_calls=[ToolCall('forbidden', 'summarize_capture', {})]), 'tool_calls')]:
            with self.subTest(kind=kind):
                result = self.run_provider(FinalizingProvider([response]), max_finalization_attempts=1)
                self.assertEqual(result.status, 'conclusion_validation_error')
                self.assertEqual(result.turn_trace[-1]['response_kind'], kind)
                self.assertNotIn('forbidden', [e['id'] for e in result.trace])

    def test_no_evidence_remains_bounded_and_diagnostics_hide_text(self):
        provider = fixtures.ScriptProvider([ModelResponse(text='private reasoning sk-hidden-example'), ModelResponse()])
        result = self.run_provider(provider, max_turns=2)
        self.assertEqual(result.status, 'max_turns')
        self.assertEqual([e['response_kind'] for e in result.turn_trace], ['plain_text', 'empty'])
        self.assertNotIn('private reasoning', json.dumps(asdict(result)))
        self.assertNotIn('sk-hidden-example', json.dumps(asdict(result)))

    def test_each_retry_attempt_has_diagnostics(self):
        class TransientError(Exception):
            code = 503
        fake = FinalizingProvider()
        calls = 0

        class Provider:
            def respond(self, *args):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise TransientError('503 UNAVAILABLE\nAuthorization: Bearer private-key')
                return fake.respond(*args)

        result = self.run_provider(Provider(), retry_sleep=lambda _: None)
        self.assertEqual(result.status, 'complete')
        self.assertEqual(len(result.turn_trace), result.provider_attempts)
        self.assertEqual([e['turn'] for e in result.turn_trace[:2]], [1, 1])
        self.assertNotIn('private-key', json.dumps(result.turn_trace))

    def test_chat_completion_finalization_request_contains_no_tools(self):
        from canary.llm.openrouter import OpenRouterProvider
        from canary.llm.base import Message
        stub = wire_fixtures.StubHTTP([(200, wire_fixtures.wire(text='{}'))])
        with patch.dict('os.environ', {'OPENROUTER_API_KEY': 'stub-key-only'}), \
                patch('canary.llm.openrouter.HTTPSConnection', stub):
            OpenRouterProvider('stub-model').respond(FINALIZATION, [Message('user', {})], [], CONCLUSION_SCHEMA)
        self.assertNotIn('tools', stub.requests[0])
        self.assertNotIn('tool_choice', stub.requests[0])
        self.assertEqual(stub.requests[0]['response_format'], {'type': 'json_object'})

    def test_gemini_finalization_overrides_chat_tools(self):
        from canary.llm.gemini import GeminiProvider
        from types import SimpleNamespace
        from unittest.mock import Mock
        provider = GeminiProvider.__new__(GeminiProvider)
        provider.types = SimpleNamespace(GenerateContentConfig=SimpleNamespace,
            AutomaticFunctionCallingConfig=SimpleNamespace)
        provider.chat = Mock()
        provider.chat.send_message.return_value = SimpleNamespace(candidates=[SimpleNamespace(
            content=SimpleNamespace(parts=[]))])
        provider.cursor, provider.pending_conclusion = 0, False
        provider.respond(FINALIZATION, [], [], CONCLUSION_SCHEMA)
        config = provider.chat.send_message.call_args.kwargs['config']
        self.assertEqual(config.tools, [])
        self.assertEqual(config.response_json_schema, CONCLUSION_SCHEMA)
