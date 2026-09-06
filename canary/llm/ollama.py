"""Ollama local/cloud-via-daemon transport; authentication stays with Ollama."""

from http.client import HTTPConnection, HTTPSConnection
import json
import os
from urllib.parse import urlsplit

from .chat_completions import ChatCompletionsProvider
from .errors import provider_error


DEFAULT_BASE_URL = 'http://localhost:11434'


class OllamaError(Exception):
    def __init__(self, status_code, message):
        self.status_code = status_code
        super().__init__(message)


class OllamaProvider(ChatCompletionsProvider):
    provider_name = 'Ollama'

    def __init__(self, model=None, *, max_tokens=None):
        if not isinstance(model, str) or not model.strip():
            raise ValueError('Ollama requires --model with a nonempty model name')
        if max_tokens is not None and (type(max_tokens) is not int or max_tokens <= 0):
            raise ValueError('Ollama max_tokens must be a positive integer or None')
        base = os.environ.get('OLLAMA_BASE_URL', DEFAULT_BASE_URL)
        try:
            url = urlsplit(base)
            if (url.scheme not in ('http', 'https') or not url.hostname or url.username is not None
                    or url.password is not None or url.query or url.fragment
                    or any(c.isspace() or ord(c) < 32 for c in base)):
                raise ValueError
            self._host, self._port = url.hostname, url.port
        except ValueError:
            raise ValueError('OLLAMA_BASE_URL must be an HTTP(S) base URL without credentials, query or fragment') from None
        path = url.path.rstrip('/')
        self._path = path + ('/chat/completions' if path.endswith('/v1') else '/v1/chat/completions')
        self._scheme, self.model, self.max_tokens = url.scheme, model, max_tokens
        self.base_url = base.rstrip('/')
        super().__init__()

    def _request(self, payload):
        # Cloud model names are passed unchanged to the daemon, which owns its
        # sign-in/session. CANary neither reads nor sends an Ollama credential.
        body = dict(payload)
        if self.max_tokens is not None:
            body['max_tokens'] = self.max_tokens
        connection_type = HTTPSConnection if self._scheme == 'https' else HTTPConnection
        connection = connection_type(self._host, self._port, timeout=300)
        try:
            connection.request('POST', self._path, body=json.dumps(body, allow_nan=False).encode('utf-8'),
                               headers={'Content-Type': 'application/json'})
            response = connection.getresponse()
            try:
                result = json.loads(response.read())
            except (ValueError, UnicodeError):
                if response.status >= 400:
                    raise OllamaError(response.status, f'Ollama HTTP {response.status}') from None
                raise ValueError('Ollama returned invalid JSON') from None
            error = result.get('error') if isinstance(result, dict) else None
            if response.status != 200 or error:
                status = response.status
                detail = error.get('message') if isinstance(error, dict) else error
                if status == 200 and isinstance(error, dict) and type(error.get('code')) is int:
                    status = error['code']
                message = f'Ollama HTTP {status}' + (': ' + detail if isinstance(detail, str) else '')
                message = provider_error(OllamaError(status, message))['message']
                raise OllamaError(status, message)
            return result
        finally:
            connection.close()
