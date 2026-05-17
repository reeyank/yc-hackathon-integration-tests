import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from network_capture import NetworkEvent  # noqa: E402
from run_report import build_run_report, visual_review  # noqa: E402
from trace import Action, Flow, Step, Target, Trace  # noqa: E402


def test_build_run_report_includes_flow_network_and_improvements(tmp_path):
    trace = Trace(app_path="DemoApp")
    trace.flows.append(
        Flow(
            name="create_item",
            status="passed",
            gbrain_symbols=["CreateItemScreen"],
            steps=[
                Step(action=Action.LAUNCH),
                Step(
                    action=Action.TAP,
                    target=Target(a11y_id="save-item-btn"),
                    screenshot="screen.png",
                ),
            ],
        )
    )
    (tmp_path / "screen.png").write_bytes(b"not-real-png")

    report = build_run_report(
        trace=trace,
        trace_dir=tmp_path,
        network_events=[NetworkEvent("POST", "https://api.example.test/save", status=500)],
        tool_history=[{"tool": "tap", "status": "done", "result": "save-item-btn"}],
        visual_notes="- Visible create form looked usable.",
        trace_path=tmp_path / "trace.json",
    )

    assert "`create_item`: `passed`" in report
    assert "## GBrain Backbone" in report
    assert "CreateItemScreen" in report
    assert "`POST` `https://api.example.test/save` returned `500`" in report
    assert "Visible create form looked usable" in report


def test_visual_review_without_screenshots_is_local():
    trace = Trace(app_path="DemoApp", flows=[Flow(name="empty")])

    review = visual_review(trace, "/tmp/does-not-matter")

    assert "No screenshots" in review
