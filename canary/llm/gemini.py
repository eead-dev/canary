"""Optional official Google Gen AI SDK adapter with manual tool execution."""

import json
import os

from .base import ModelResponse, ToolCall

DEFAULT_MODEL = "gemini-3.7-flash"


class GeminiProvider:
    """One provider instance per agent run; SDK chat retains thought signatures."""

    def __init__(self, model: str = DEFAULT_MODEL):
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise ValueError("GEMINI_API_KEY must be set")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a nonempty string")
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise ValueError("Install the optional Gemini extra: python -m pip install -e .[gemini]") from None
        self.types = types
        try:
            self.client = genai.Client(api_key=key, vertexai=False, http_options=types.HttpOptions(timeout=60000))
        except Exception:
            raise ValueError("Gemini client initialization failed; check SDK and environment configuration") from None
        self.model, self.chat, self.cursor, self.sequence = model, None, 0, 0
        self.call_ids = {}
        self.pending_conclusion = False
        self.conclusion_id = None

    def respond(self, system, messages, tools, conclusion_schema):
        types = self.types
        if self.chat is None:
            declarations = [types.FunctionDeclaration(name=t["name"], description=t["description"],
                            parameters_json_schema=t["parameters"]) for t in tools]
            declarations.append(types.FunctionDeclaration(name="submit_conclusion", description="Submit the final evidence-based conclusion.",
                                                           parameters_json_schema=conclusion_schema))
            self.chat = self.client.chats.create(model=self.model, config=types.GenerateContentConfig(
                system_instruction=system, tools=[types.Tool(function_declarations=declarations)],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)))
        parts = []
        for message in messages[self.cursor:]:
            if message.role == "user":
                if self.pending_conclusion and "error" in message.content:
                    fields = {"name": "submit_conclusion", "response": message.content}
                    if self.conclusion_id:
                        fields["id"] = self.conclusion_id
                    parts.append(types.Part(function_response=types.FunctionResponse(**fields)))
                    self.pending_conclusion = False
                else:
                    parts.append(types.Part.from_text(text=json.dumps(message.content, allow_nan=False)))
            elif message.role == "tool":
                event = message.content
                fields = {"name": event["name"], "response": event["output"]}
                if self.call_ids.get(event["id"]):
                    fields["id"] = self.call_ids[event["id"]]
                parts.append(types.Part(function_response=types.FunctionResponse(**fields)))
        self.cursor = len(messages)
        response = self.chat.send_message(parts)
        calls, texts, conclusion = [], [], None
        for part in response.candidates[0].content.parts:
            if part.function_call:
                fc = part.function_call
                self.sequence += 1
                if fc.name == "submit_conclusion":
                    if conclusion is not None:
                        raise ValueError("multiple conclusions in one response")
                    conclusion = dict(fc.args or {})
                    self.pending_conclusion = True
                    self.conclusion_id = getattr(fc, "id", None)
                else:
                    self.call_ids[str(self.sequence)] = getattr(fc, "id", None)
                    calls.append(ToolCall(str(self.sequence), fc.name, dict(fc.args or {})))
            elif part.text and not getattr(part, "thought", False):
                texts.append(part.text)
        return ModelResponse(text="\n".join(texts), tool_calls=calls, conclusion=conclusion)

    def close(self):
        self.client.close()
