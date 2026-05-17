import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_decider import OpenAIConfigurationError, OpenAIDecider, parse_decision  # noqa: E402


def test_parse_decision_structured_json():
    decision = parse_decision(
        """
        {
          "summary": "Auth is blocking the flow.",
          "confidence": 0.82,
          "risks": ["OTP required"],
          "tool_calls": [
            {"name": "ask_user", "arguments": {"field": "otp"}, "reason": "Phone auth is visible"}
          ]
        }
        """
    )

    assert decision.summary == "Auth is blocking the flow."
    assert decision.confidence == 0.82
    assert decision.tool_calls[0].name == "ask_user"


def test_decider_fails_loud_without_openai_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(OpenAIConfigurationError):
        OpenAIDecider()
