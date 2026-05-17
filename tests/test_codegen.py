"""Fixture-driven codegen unit test (T7).

Demo-critical, pure function, no simulator. Loads the nasty fixture, runs
codegen, asserts the output is valid JS (node --check) and that the edge
cases survived: unicode/quotes escaped, missing-a11y_id fell back to a label
selector, empty-assertion flow still produced a valid it().

The trace-schema round-trip test guards the locked contract; the codegen
tests now run for real because T6 is implemented.
"""

import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trace import Trace  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "trace_nasty.json")


def test_trace_schema_roundtrip():
    """trace.py is real: load -> serialize -> reload is lossless and the
    nasty unicode/quote value survives. This guards the locked contract."""
    t = Trace.load(FIXTURE)
    assert t.schema_version == 1
    assert [f.name for f in t.flows] == ["create_item", "empty_assertions_flow"]
    nasty = t.flows[0].steps[2].value
    assert "O'Brien" in nasty and '"quoted"' in nasty and "日本語" in nasty
    # round-trip
    again = Trace.from_dict(json.loads(t.to_json()))
    assert again.flows[0].steps[2].value == nasty
    assert again.flows[0].steps[1].target.resolved_by == "a11y_id"
    assert again.flows[0].steps[3].target.coord == (180.5, 642.0)


def test_trace_roundtrip_preserves_flow_coverage_metadata():
    from trace import Flow

    t = Trace(app_path="app", flows=[Flow(name="settings", route="/settings", source_file="app/settings.tsx", kind="route")])

    again = Trace.from_dict(json.loads(t.to_json()))

    assert again.flows[0].route == "/settings"
    assert again.flows[0].source_file == "app/settings.tsx"
    assert again.flows[0].kind == "route"


def test_codegen_emits_valid_js():
    from codegen_detox import generate

    js = generate(Trace.load(FIXTURE))
    # unicode/quotes must be escaped, not raw-injected
    assert "O'Brien" not in js or "\\'" in js or "\\u" in js
    # node parses it
    p = subprocess.run(
        ["node", "--check", "-"], input=js, text=True, capture_output=True
    )
    assert p.returncode == 0, p.stderr


def test_codegen_handles_edge_cases():
    from codegen_detox import generate

    js = generate(Trace.load(FIXTURE))
    assert "describe(" in js and js.count("it(") == 2  # one it() per flow
    assert "by.label('Title')" in js  # missing a11y_id -> label fallback
    assert "coord:180.5,642.0" in js  # brittle selector is visible for patching
