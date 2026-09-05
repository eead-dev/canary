"""Provider-neutral conversation and response contracts."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Message:
    role: str
    content: dict


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class ModelResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    conclusion: dict | None = None


class ModelProvider(Protocol):
    def respond(self, system: str, messages: list[Message], tools: list[dict],
                conclusion_schema: dict) -> ModelResponse: ...
