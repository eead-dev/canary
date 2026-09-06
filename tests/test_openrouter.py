from contextlib import redirect_stdout, redirect_stderr
from dataclasses import asdict
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from canary.agent import CONCLUSION_SCHEMA, run_agent
from canary.agent_cli import main
from canary.llm.base import Message
from canary.llm.fake import FakeProvider
from canary.llm.openrouter import OpenRouterProvider, OpenRouterError
from canary.llm.errors import provider_error
from canary.llm.retry import RetryingProvider


def wire(calls=(), text=None):
    return {'choices': [{'finish_reason': 'tool_calls' if calls else 'stop',
                        'message': {'role': 'assistant', 'content': text,
                                    'tool_calls': list(calls)}}]}


def call(identity, name, arguments):
    return {'id': identity, 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(arguments)}}


class StubHTTP:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []
        self.closed = 0

    def __call__(self, host, timeout):
        assert host == 'openrouter.ai' and timeout == 60
        return self

    def request(self, method, path, body, headers):
        assert method == 'POST' and path == '/api/v1/chat/completions'
        assert headers['Authorization'] == 'Bearer stub-key-only'
        self.requests.append(json.loads(body))

    def getresponse(self):
        status, body = next(self.responses)
        return Mock(status=status, read=lambda: body if isinstance(body, bytes) else json.dumps(body).encode())

    def close(self):
        self.closed += 1


class OpenRouterTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {'OPENROUTER_API_KEY': 'stub-key-only'})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_construction_credentials_and_model(self):
        self.assertEqual(OpenRouterProvider('vendor/model-a').model, 'vendor/model-a')
        self.assertEqual(OpenRouterProvider('other/model-b').model, 'other/model-b')
        for model in (None, '', ' ', 1):
            with self.assertRaisesRegex(ValueError, '--model'):
                OpenRouterProvider(model)
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'not-an-openrouter-key'}, clear=True):
            with self.assertRaisesRegex(ValueError, 'OPENROUTER_API_KEY'):
                OpenRouterProvider('vendor/model')

    def test_request_tools_continuation_and_conclusion_correction(self):
        tool = {'name': 'summarize_capture', 'description': 'Capture summary',
                'parameters': {'type': 'object', 'properties': {}}}
        first = wire([call('call-1', tool['name'], {})])
        first['choices'][0]['message']['reasoning_details'] = [{'type': 'reasoning.text', 'text': 'opaque fixture'}]
        stub = StubHTTP([(200, first), (200, wire([call('final-1', 'submit_conclusion', {'invalid': True})])),
                         (200, wire([call('final-2', 'submit_conclusion', {'corrected': True})]))])
        provider = OpenRouterProvider('vendor/model')
        messages = [Message('user', {'task': 'inspect'})]
        with patch('canary.llm.openrouter.HTTPSConnection', stub):
            result = provider.respond('system', messages, [tool], CONCLUSION_SCHEMA)
            self.assertEqual(asdict(result.tool_calls[0]), {'id': 'call-1', 'name': 'summarize_capture', 'arguments': {}})
            messages.extend([Message('assistant', asdict(result)), Message('tool', {
                'id': 'call-1', 'name': tool['name'], 'output': {'ok': True, 'result': {'total_frames': 4}}})])
            result = provider.respond('system', messages, [tool], CONCLUSION_SCHEMA)
            self.assertEqual(result.conclusion, {'invalid': True})
            messages.append(Message('user', {'error': {'message': 'invalid conclusion'}}))
            self.assertEqual(provider.respond('system', messages, [tool], CONCLUSION_SCHEMA).conclusion, {'corrected': True})
        request = stub.requests[0]
        self.assertEqual(request['model'], 'vendor/model')
        self.assertEqual(request['messages'][0], {'role': 'system', 'content': 'system'})
        self.assertEqual(request['tools'][0], {'type': 'function', 'function': tool})
        self.assertEqual(request['tools'][-1]['function']['parameters'], CONCLUSION_SCHEMA)
        self.assertNotIn('stub-key-only', json.dumps(request))
        continuation = stub.requests[1]['messages']
        self.assertEqual([m['role'] for m in continuation], ['system', 'user', 'assistant', 'tool'])
        self.assertEqual(continuation[-1]['tool_call_id'], 'call-1')
        self.assertEqual(continuation[-2]['reasoning_details'], first['choices'][0]['message']['reasoning_details'])
        self.assertEqual(stub.requests[2]['messages'][-1]['tool_call_id'], 'final-1')
        self.assertEqual(stub.closed, 3)

    def test_malformed_responses(self):
        bad = [{}, {'choices': []}, wire(), wire([call('1', 'tool', [])]),
               wire([call('same', 'tool', {}), call('same', 'tool', {})])]
        malformed_args = wire([call('1', 'tool', {})])
        malformed_args['choices'][0]['message']['tool_calls'][0]['function']['arguments'] = '{bad json'
        bad.append(malformed_args)
        for value in bad:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'Malformed OpenRouter'):
                OpenRouterProvider._parse(value)
        stub = StubHTTP([(200, b'not JSON')])
        with patch('canary.llm.openrouter.HTTPSConnection', stub), self.assertRaisesRegex(ValueError, 'invalid JSON'):
            OpenRouterProvider('vendor/model').respond('system', [], [], CONCLUSION_SCHEMA)

    def test_text_only_assistant_continuation_omits_empty_calls(self):
        for calls in (None, []):
            response = wire(text='Need more evidence')
            response['choices'][0]['message']['tool_calls'] = calls
            stub = StubHTTP([(200, response), (200, wire([call('1', 'summarize_capture', {})]))])
            provider = OpenRouterProvider('vendor/model')
            messages = [Message('user', {'task': 'inspect'})]
            with patch('canary.llm.openrouter.HTTPSConnection', stub):
                provider.respond('system', messages, [], CONCLUSION_SCHEMA)
                messages.append(Message('user', {'error': {'message': 'Use tools or submit conclusion'}}))
                provider.respond('system', messages, [], CONCLUSION_SCHEMA)
            assistant = stub.requests[1]['messages'][2]
            self.assertEqual(assistant, {'role': 'assistant', 'content': 'Need more evidence'})

    def test_retry_preserves_pending_tool_turn(self):
        for status in (429, 503):
            stub = StubHTTP([(200, wire([call('1', 'summarize_capture', {})])),
                             (status, {'error': {'message': 'temporarily unavailable'}}), (200, wire(text='continue'))])
            base = OpenRouterProvider('vendor/model')
            sleep = Mock()
            provider = RetryingProvider(base, sleep=sleep, jitter=lambda lo, hi: hi)
            messages = [Message('user', {'task': 'inspect'})]
            with patch('canary.llm.openrouter.HTTPSConnection', stub):
                provider.respond('system', messages, [], CONCLUSION_SCHEMA)
                messages.append(Message('tool', {'id': '1', 'name': 'summarize_capture', 'output': {'ok': True}}))
                provider.respond('system', messages, [], CONCLUSION_SCHEMA)
            self.assertEqual(stub.requests[1], stub.requests[2])
            self.assertEqual(provider.retry_count, 1)
            self.assertEqual(provider.provider_attempts, 3)
            sleep.assert_called_once()

    def test_sanitized_errors_and_permanent_no_retry(self):
        stub = StubHTTP([(401, {'error': {'message': 'Authentication failed\nAuthorization: Bearer stub-key-only\n'
                                                     'secret: never-display-this'}})])
        sleep = Mock()
        with patch('canary.llm.openrouter.HTTPSConnection', stub), self.assertRaises(OpenRouterError) as raised:
            RetryingProvider(OpenRouterProvider('vendor/model'), sleep=sleep).respond('system', [], [], CONCLUSION_SCHEMA)
        diagnostic = provider_error(raised.exception)
        self.assertEqual(diagnostic['type'], 'OpenRouterError')
        self.assertEqual(raised.exception.status_code, 401)
        self.assertIn('OpenRouter HTTP', diagnostic['message'])
        self.assertNotIn('stub-key-only', json.dumps(diagnostic))
        self.assertNotIn('never-display-this', json.dumps(diagnostic))
        self.assertNotIn('Authorization', json.dumps(diagnostic))
        sleep.assert_not_called()

    def fixture(self, directory):
        can, ref = Path(directory)/'can.csv', Path(directory)/'reference.csv'
        can.write_text('timestamp,can_id,data\n' + ''.join(f'{i},291,{i.to_bytes(8,"little").hex()}\n' for i in range(4)))
        ref.write_text('timestamp,value\n0,5\n1,7\n2,9\n3,11\n')
        return can, ref

    def replay(self, directory):
        responses = []
        class RecordingFake(FakeProvider):
            def respond(self, *args):
                response = super().respond(*args)
                calls = [call(c.id, c.name, c.arguments) for c in response.tool_calls]
                if response.conclusion is not None:
                    calls.append(call('final', 'submit_conclusion', response.conclusion))
                responses.append((200, wire(calls, response.text or None)))
                return response
        can, ref = self.fixture(directory)
        expected = run_agent(can, ref, 'value', RecordingFake())
        return can, ref, expected, responses

    def test_provider_independent_complete_agent_and_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            can, ref, expected, responses = self.replay(directory)
            stub = StubHTTP(responses)
            with patch('canary.llm.openrouter.HTTPSConnection', stub):
                actual = run_agent(can, ref, 'value', OpenRouterProvider('vendor/model'))
            self.assertEqual(actual.status, 'complete')
            self.assertEqual(actual.conclusion, expected.conclusion)
            self.assertEqual([e['name'] for e in actual.trace], [e['name'] for e in expected.trace])
            self.assertNotIn('stub-key-only', json.dumps(asdict(actual), allow_nan=False))
            with patch('canary.llm.openrouter.HTTPSConnection', StubHTTP(responses)), \
                 patch('sys.argv', ['agent', str(can), str(ref), '--value-column', 'value',
                                    '--provider', 'openrouter', '--model', 'vendor/model']), redirect_stdout(io.StringIO()) as out:
                main()
            self.assertEqual(json.loads(out.getvalue())['conclusion'], asdict(expected.conclusion))

    def test_cli_requires_explicit_openrouter_model(self):
        with patch('sys.argv', ['agent', 'can.csv', 'ref.csv', '--value-column', 'value', '--provider', 'openrouter']), \
             redirect_stderr(io.StringIO()) as error, self.assertRaises(SystemExit):
            main()
        self.assertIn('--model', error.getvalue())

    def test_agent_provider_error_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            can, ref = self.fixture(directory)
            stub = StubHTTP([(400, {'error': {'message': 'Invalid model\nAuthorization: stub-key-only'}})])
            with patch('canary.llm.openrouter.HTTPSConnection', stub):
                result = run_agent(can, ref, 'value', OpenRouterProvider('vendor/model'))
            self.assertEqual(result.status, 'provider_error')
            self.assertEqual(result.error['type'], 'OpenRouterError')
            self.assertIn('Invalid model', result.error['message'])
            self.assertNotIn('stub-key-only', json.dumps(asdict(result)))
