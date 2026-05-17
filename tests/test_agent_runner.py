import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import agent_runner  # noqa: E402
from ai_decider import AgentDecision, ToolCall  # noqa: E402
from trace import Action, Flow, Step  # noqa: E402


def test_gbrain_context_uses_hybrid_query(monkeypatch):
    calls = []

    def fake_gbrain(*args):
        calls.append(args)
        return "answer", None

    monkeypatch.setattr(agent_runner, "_try_gbrain", fake_gbrain)

    hits = agent_runner._gbrain_context()

    assert hits
    assert all(call[0] == "query" for call in calls)
    assert any("hybrid-query" in hit for hit in hits)


class FakeTUI:
    def __init__(self):
        self.logs = []

    def log(self, title, detail):
        self.logs.append((title, detail))

    def ask(self, prompt, password=False):
        return "123456" if password else "test"


class FakeIdb:
    def __init__(self):
        self.tree = {
            "children": [
                {
                    "AXLabel": "Continue",
                    "frame": {"x": 10, "y": 20, "width": 100, "height": 40},
                }
            ]
        }

    def observe(self):
        return self.tree, "screen.png"

    def act(self, step):
        return self.tree


def test_execute_tool_calls_queries_gbrain_and_records_assertion(monkeypatch):
    monkeypatch.setattr(agent_runner, "_try_gbrain", lambda *args: ("hit auth flow", None))
    flow = Flow(name="agent")
    flow.steps.append(Step(action=Action.LAUNCH))
    history = []
    decision = AgentDecision(
        summary="Need more context",
        confidence=0.8,
        risks=[],
        tool_calls=[
            ToolCall(name="query_gbrain", arguments={"query": "auth flow"}, reason="source context"),
            ToolCall(name="assert_visible", arguments={"selector": "Continue"}, reason="button should show"),
        ],
    )

    result = agent_runner._execute_tool_calls(
        decision,
        FakeTUI(),
        flow,
        FakeIdb(),
        FakeIdb().tree,
        lambda: [],
        history,
        {},
    )

    assert result["stopped"] is False
    assert any("agent-query" in hit for hit in flow.gbrain_evidence)
    assert flow.steps[-1].assertions[0].selector == "Continue"
    assert [entry["tool"] for entry in history] == ["query_gbrain", "assert_visible"]
