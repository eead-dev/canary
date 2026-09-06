"""Standard-library OpenRouter chat-completions adapter; no tool execution."""

from http.client import HTTPSConnection
import json
import os

from .chat_completions import ChatCompletionsProvider
from .errors import provider_error


class OpenRouterError(Exception):
    def __init__(self, status_code, message):
        self.status_code = status_code
        super().__init__(message)


class OpenRouterProvider(ChatCompletionsProvider):
    """One explicit model and conversation per run; retries belong to the caller."""

    provider_name = 'OpenRouter'

    def __init__(self, model=None):
        if not isinstance(model, str) or not model.strip():
            raise ValueError('OpenRouter requires --model with a nonempty model ID')
        key = os.environ.get('OPENROUTER_API_KEY')
        if not key or not key.strip():
            raise ValueError('OPENROUTER_API_KEY must be set')
        self.model, self._key = model, key
        super().__init__()

    def _request(self, payload):
        # Fixed HTTPS endpoint; no redirects or cross-host credential forwarding.
        connection = HTTPSConnection('openrouter.ai', timeout=60)
        try:
            connection.request('POST', '/api/v1/chat/completions',
                               body=json.dumps(payload, allow_nan=False).encode('utf-8'),
                               headers={'Authorization': 'Bearer ' + self._key,
                                        'Content-Type': 'application/json'})
            response = connection.getresponse()
            body = response.read()
            try:
                result = json.loads(body)
            except (ValueError, UnicodeError):
                if response.status >= 400:
                    raise OpenRouterError(response.status, f'OpenRouter HTTP {response.status}') from None
                raise ValueError('OpenRouter returned invalid JSON') from None
            error = result.get('error') if isinstance(result, dict) else None
            if response.status != 200 or error:
                status = response.status
                message = f'OpenRouter HTTP {status}'
                if isinstance(error, dict):
                    if status == 200 and type(error.get('code')) is int:
                        status = error['code']
                    if isinstance(error.get('message'), str):
                        message = f'OpenRouter HTTP {status}: ' + error['message']
                # Sanitize here as well as at the agent boundary. Never retain
                # response headers, request objects, or raw error bodies in errors.
                message = message.replace(self._key, '[REDACTED]')
                message = provider_error(OpenRouterError(status, message))['message']
                raise OpenRouterError(status, message)
            return result
        finally:
            connection.close()
