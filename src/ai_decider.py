"""OpenAI-backed planning for the gbrain integration test agent.

The deterministic trace runner stays the demo contract. This module is the
AI layer that reasons over gbrain provenance, live accessibility state, and
network evidence to decide what the tester should try next.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


DEFAULT_MODEL = "gpt-5.4"


class OpenAIConfigurationError(RuntimeError):
    """The OpenAI client cannot be constructed from the current environment."""


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass
class AgentDecision:
    summary: str
    confidence: float
    risks: list[str]
    tool_calls: list[ToolCall]


def openai_ready() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def model_name() -> str:
    return os.environ.get("IOS_TEST_OPENAI_MODEL", DEFAULT_MODEL)


class OpenAIDecider:
    def __init__(self, model: str | None = None) -> None:
        if not openai_ready():
            raise OpenAIConfigurationError(
                "OPENAI_API_KEY is not visible to ios-test. Export it in the shell "
                "that runs `ios-test`, or set it before launching Codex."
            )
        try:
            from openai import OpenAI
        except ModuleNotFoundError as e:
            raise OpenAIConfigurationError(
                "The `openai` package is not installed. Run `pip install -e .` "
                "or reinstall the project dependencies."
            ) from e
        self.model = model or model_name()
        self.client = OpenAI()

    def decide(self, context: dict[str, Any]) -> AgentDecision:
        response = self.client.responses.create(
            model=self.model,
            instructions=_instructions(),
            input=json.dumps(context, indent=2, sort_keys=True),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "ios_test_agent_decision",
                    "strict": True,
                    "schema": _schema(),
                }
            },
        )
        return parse_decision(response.output_text)


def parse_decision(text: str) -> AgentDecision:
    raw = json.loads(text)
    return AgentDecision(
        summary=str(raw["summary"]),
        confidence=float(raw["confidence"]),
        risks=[str(item) for item in raw["risks"]],
        tool_calls=[
            ToolCall(
                name=str(item["name"]),
                arguments={
                    str(key): value
                    for key, value in dict(item.get("arguments", {})).items()
                    if value is not None
                },
                reason=str(item.get("reason", "")),
            )
            for item in raw["tool_calls"]
        ],
    )


def _instructions() -> str:
    return (
        "You are the planning brain for an iOS React Native integration tester. "
        "Use gbrain evidence as the source of truth for intended flows, live "
        "accessibility labels as the source of truth for what is actually on "
        "screen, and network events as the source of truth for backend health. "
        "Prefer stable selectors over coordinates. If authentication blocks the "
        "flow, request user input through ask_user instead of guessing secrets. "
        "Never claim a test passed unless the visible UI or network evidence "
        "supports it. Return only the structured decision."
    )


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["summary", "confidence", "risks", "tool_calls"],
        "properties": {
            "summary": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "risks": {"type": "array", "items": {"type": "string"}},
            "tool_calls": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "arguments", "reason"],
                    "properties": {
                        "name": {
                            "type": "string",
                            "enum": [
                                "observe_ui",
                                "tap",
                                "type_text",
                                "swipe",
                                "ask_user",
                                "query_gbrain",
                                "inspect_network",
                                "assert_visible",
                                "stop",
                            ],
                        },
                        "arguments": _arguments_schema(),
                        "reason": {"type": "string"},
                    },
                },
            },
        },
    }


def _arguments_schema() -> dict[str, Any]:
    fields = {
        "field": {"type": ["string", "null"]},
        "prompt": {"type": ["string", "null"]},
        "selector": {"type": ["string", "null"]},
        "text": {"type": ["string", "null"]},
        "direction": {"type": ["string", "null"]},
        "query": {"type": ["string", "null"]},
        "kind": {"type": ["string", "null"]},
        "expected": {"type": ["string", "null"]},
        "path": {"type": ["string", "null"]},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(fields),
        "properties": fields,
    }
