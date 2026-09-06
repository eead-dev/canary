"""Shared chat-completions message mapping; transport stays in each adapter."""

import json

from .base import ModelResponse, ToolCall


class ChatCompletionsProvider:
    provider_name = 'chat-completions'

    def __init__(self):
        self._history, self._pending, self._cursor = [], [], 0

    @classmethod
    def _parse(cls, result):
        try:
            choices = result['choices']
            if not isinstance(choices, list) or len(choices) != 1:
                raise ValueError
            choice = choices[0]
            if choice.get('finish_reason') not in ('stop', 'tool_calls'):
                raise ValueError
            message = choice['message']
            if message.get('role') != 'assistant':
                raise ValueError
            text = message.get('content')
            if text is not None and not isinstance(text, str):
                raise ValueError
            raw_calls = message.get('tool_calls', [])
            if raw_calls is None:
                raw_calls = []
            if not isinstance(raw_calls, list):
                raise ValueError
            calls, conclusion, ids = [], None, set()
            for call in raw_calls:
                identity, function = call['id'], call['function']
                if call['type'] != 'function' or not isinstance(identity, str) or not identity or identity in ids:
                    raise ValueError
                ids.add(identity)
                name = function['name']
                if not isinstance(name, str) or not name or not isinstance(function['arguments'], str):
                    raise ValueError
                arguments = json.loads(function['arguments'])
                if not isinstance(arguments, dict):
                    raise ValueError
                if name == 'submit_conclusion':
                    if conclusion is not None:
                        raise ValueError
                    conclusion = arguments
                else:
                    calls.append(ToolCall(identity, name, arguments))
            if not raw_calls and not text:
                raise ValueError
            saved = {k: message[k] for k in ('role', 'content', 'reasoning_details') if k in message}
            if raw_calls:
                saved['tool_calls'] = raw_calls
            return ModelResponse(text=text or '', tool_calls=calls, conclusion=conclusion), saved, [c['id'] for c in raw_calls]
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ValueError(f'Malformed {cls.provider_name} chat-completions response') from None

    def respond(self, system, messages, tools, conclusion_schema):
        # Stage locally. A failed request must leave the cursor, pending IDs and
        # conversation untouched so RetryingProvider resends the identical turn.
        history, pending = list(self._history), list(self._pending)
        for message in messages[self._cursor:]:
            if message.role == 'tool':
                event = message.content
                history.append({'role': 'tool', 'tool_call_id': event['id'],
                                'content': json.dumps(event['output'], allow_nan=False)})
                if event['id'] in pending:
                    pending.remove(event['id'])
            elif message.role == 'user':
                if pending and 'error' in message.content:
                    # Rejected conclusions (or mixed conclusion/tool responses)
                    # get tool acknowledgments before the next model turn.
                    history.extend({'role': 'tool', 'tool_call_id': identity,
                                    'content': json.dumps(message.content, allow_nan=False)} for identity in pending)
                    pending = []
                else:
                    history.append({'role': 'user', 'content': json.dumps(message.content, allow_nan=False)})
            # Assistant wire messages are already retained from API responses.
        definitions = [{'type': 'function', 'function': dict(tool)} for tool in tools]
        definitions.append({'type': 'function', 'function': {
            'name': 'submit_conclusion', 'description': 'Submit the final evidence-based conclusion.',
            'parameters': conclusion_schema}})
        payload = {'model': self.model, 'messages': [{'role': 'system', 'content': system}, *history],
                   'tools': definitions, 'tool_choice': 'auto', 'stream': False}
        if not tools and 'Return only a valid AgentDecision using the evidence already gathered.' in system:
            payload.pop('tools')
            payload.pop('tool_choice')
            payload['response_format'] = {'type': 'json_object'}
            payload['messages'][0]['content'] += '\nFinal response schema: ' + json.dumps(conclusion_schema)
        response, assistant, next_pending = self._parse(self._request(payload))
        self._history, self._pending, self._cursor = [*history, assistant], next_pending, len(messages)
        return response
