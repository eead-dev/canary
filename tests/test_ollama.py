from contextlib import redirect_stdout, redirect_stderr
from dataclasses import asdict
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch, Mock

from canary.agent import CONCLUSION_SCHEMA, run_agent
from canary.agent_cli import main
from canary.llm.base import Message
from canary.llm.ollama import OllamaProvider, OllamaError
from canary.llm.retry import RetryingProvider
from tests import test_openrouter as fixtures


class StubOllamaHTTP(fixtures.StubHTTP):
    def __init__(self, responses):
        super().__init__(responses)
        self.connections, self.paths = [], []

    def __call__(self, host, port, timeout):
        self.connections.append((host, port, timeout))
        return self

    def request(self, method, path, body, headers):
        assert method == 'POST'
        assert headers == {'Content-Type': 'application/json'}
        self.paths.append(path)
        self.requests.append(json.loads(body))


class OllamaTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def test_local_and_cloud_names_without_credentials(self):
        for model in ('gpt-oss:20b', 'glm-4.7-flash', 'qwen3-coder:480b-cloud', 'gpt-oss:120b-cloud'):
            provider = OllamaProvider(model)
            self.assertEqual(provider.model, model)
            self.assertEqual(provider.base_url, 'http://localhost:11434')
            self.assertIsNone(provider.max_tokens)
        for model in (None, '', ' ', 123):
            with self.assertRaisesRegex(ValueError, '--model'):
                OllamaProvider(model)

    def test_base_url_override_and_validation(self):
        for url, host, port, path, transport in (
                ('http://127.0.0.1:12345/', '127.0.0.1', 12345, '/v1/chat/completions', 'HTTPConnection'),
                ('https://example.test/proxy/v1/', 'example.test', None, '/proxy/v1/chat/completions', 'HTTPSConnection')):
            stub = StubOllamaHTTP([(200, fixtures.wire(text='text'))])
            with patch.dict(os.environ, {'OLLAMA_BASE_URL': url, 'OLLAMA_API_KEY': 'unused-key'}), \
                 patch('canary.llm.ollama.'+transport, stub):
                OllamaProvider('arbitrary-model').respond('system', [], [], CONCLUSION_SCHEMA)
            self.assertEqual(stub.connections, [(host, port, 300)])
            self.assertEqual(stub.paths, [path])
            self.assertNotIn('unused-key', json.dumps(stub.requests))
        for url in ('', 'localhost:11434', 'ftp://host', 'http://host:999999',
                    'http://user:secret@host', 'http://host?secret=value', 'http://host#fragment', 'http://host\n'):
            with patch.dict(os.environ, {'OLLAMA_BASE_URL': url}), self.assertRaisesRegex(ValueError, 'OLLAMA_BASE_URL'):
                OllamaProvider('model')

    def test_tool_mapping_continuation_and_output_limits(self):
        tool = {'name': 'summarize_capture', 'description': 'Summary',
                'parameters': {'type': 'object', 'properties': {}}}
        for limit in (None, 16384):
            stub = StubOllamaHTTP([(200, fixtures.wire([fixtures.call('id-1', tool['name'], {})])),
                                  (200, fixtures.wire([fixtures.call('final', 'submit_conclusion', {'example': True})]))])
            provider = OllamaProvider('gpt-oss:20b', max_tokens=limit)
            messages = [Message('user', {'task': 'inspect'})]
            with patch('canary.llm.ollama.HTTPConnection', stub):
                result = provider.respond('system', messages, [tool], CONCLUSION_SCHEMA)
                self.assertEqual(asdict(result.tool_calls[0]), {'id': 'id-1', 'name': tool['name'], 'arguments': {}})
                messages.extend([Message('assistant', asdict(result)), Message('tool', {
                    'id': 'id-1', 'name': tool['name'], 'output': {'ok': True}})])
                self.assertEqual(provider.respond('system', messages, [tool], CONCLUSION_SCHEMA).conclusion, {'example': True})
            for request in stub.requests:
                self.assertEqual(request['model'], 'gpt-oss:20b')
                self.assertEqual(request['tools'][0]['function'], tool)
                self.assertEqual(request['tools'][-1]['function']['parameters'], CONCLUSION_SCHEMA)
                self.assertFalse(request['stream'])
                if limit is None:
                    self.assertNotIn('max_tokens', request)
                else:
                    self.assertEqual(request['max_tokens'], limit)
            self.assertEqual([m['role'] for m in stub.requests[1]['messages']], ['system', 'user', 'assistant', 'tool'])
            self.assertEqual(stub.requests[1]['messages'][-1]['tool_call_id'], 'id-1')
            self.assertEqual(stub.closed, 2)
        for limit in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                OllamaProvider('model', max_tokens=limit)

    def test_malformed_response(self):
        for body in ({}, {'choices': []}, b'not json', fixtures.wire([fixtures.call('1', 'tool', [])])):
            stub = StubOllamaHTTP([(200, body)])
            with patch('canary.llm.ollama.HTTPConnection', stub), self.assertRaisesRegex(ValueError, 'Ollama'):
                OllamaProvider('model').respond('system', [], [], CONCLUSION_SCHEMA)

    def test_retry_same_tool_turn(self):
        stub = StubOllamaHTTP([(200, fixtures.wire([fixtures.call('1', 'tool', {})])),
                              (503, {'error': 'temporarily unavailable'}), (200, fixtures.wire(text='continue'))])
        sleep = Mock()
        provider = RetryingProvider(OllamaProvider('model'), sleep=sleep, jitter=lambda lo, hi: hi)
        messages = [Message('user', {'task': 'inspect'})]
        with patch('canary.llm.ollama.HTTPConnection', stub):
            provider.respond('system', messages, [], CONCLUSION_SCHEMA)
            messages.append(Message('tool', {'id': '1', 'output': {'ok': True}}))
            provider.respond('system', messages, [], CONCLUSION_SCHEMA)
        self.assertEqual(stub.requests[1], stub.requests[2])
        self.assertEqual(provider.retry_count, 1)
        sleep.assert_called_once()

    def test_provider_independent_agent_and_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            can, ref, expected, responses = fixtures.OpenRouterTests().replay(directory)
            stub = StubOllamaHTTP(responses)
            with patch('canary.llm.ollama.HTTPConnection', stub):
                actual = run_agent(can, ref, 'value', OllamaProvider('qwen3-coder:480b-cloud'))
            self.assertEqual(actual.status, 'complete')
            self.assertEqual(actual.conclusion, expected.conclusion)
            json.dumps(asdict(actual), allow_nan=False)
            with patch('canary.llm.ollama.HTTPConnection', StubOllamaHTTP(responses)), \
                 patch('sys.argv', ['agent', str(can), str(ref), '--provider', 'ollama',
                                    '--model', 'gpt-oss:20b', '--value-column', 'value', '--ollama-max-tokens', '16384']), \
                 redirect_stdout(io.StringIO()) as output:
                main()
            self.assertEqual(json.loads(output.getvalue())['conclusion'], asdict(expected.conclusion))

    def test_connection_failure_and_sanitized_http_error(self):
        with tempfile.TemporaryDirectory() as directory:
            can, ref = fixtures.OpenRouterTests().fixture(directory)
            connection = Mock()
            connection.request.side_effect = ConnectionRefusedError('Ollama is not running')
            with patch('canary.llm.ollama.HTTPConnection', return_value=connection):
                result = run_agent(can, ref, 'value', OllamaProvider('model'))
            self.assertEqual(result.status, 'provider_error')
            self.assertEqual(result.error['type'], 'ConnectionRefusedError')
            self.assertEqual(result.provider_attempts, 1)
            connection.close.assert_called_once()
            stub = StubOllamaHTTP([(401, {'error': {'message': 'Sign in required\nAuthorization: Bearer private-value'}})])
            with patch('canary.llm.ollama.HTTPConnection', stub):
                result = run_agent(can, ref, 'value', OllamaProvider('model'))
            self.assertEqual(result.error['type'], 'OllamaError')
            self.assertIn('Sign in required', result.error['message'])
            self.assertNotIn('private-value', json.dumps(asdict(result)))
            self.assertEqual(result.provider_attempts, 1)

    def test_cli_requires_model_and_valid_limit(self):
        for tail in ([], ['--model', 'm', '--ollama-max-tokens', '0']):
            with patch('sys.argv', ['agent', 'can.csv', 'ref.csv', '--provider', 'ollama', '--value-column', 'value', *tail]), \
                 redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main()
