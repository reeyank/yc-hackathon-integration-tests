import os
import sys

import pytest
import subprocess

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import flow_extractor  # noqa: E402
from flow_extractor import GBrainUnavailable, extract_flows  # noqa: E402


def test_extract_flows_from_gbrain_evidence(monkeypatch):
    def fake_gbrain(*args):
        if args[0] == "search":
            return "DemoApp/App.tsx: navigation uses OnboardingScreen -> ItemListScreen"
        if args[0] == "code-def":
            return f"DemoApp/App.tsx: function {args[1]}()"
        if args[0] == "code-refs":
            return f"DemoApp/App.tsx: reference {args[1]}"
        raise AssertionError(args)

    monkeypatch.setattr(flow_extractor, "_gbrain", fake_gbrain)

    flows = extract_flows("DemoApp")
    by_name = {flow.flow: flow for flow in flows}

    assert {"onboarding", "browse_items", "create_item", "settings"} <= set(by_name)
    assert "CreateItemScreen" in by_name["create_item"].gbrain_symbols
    assert "itemStore.add" in by_name["create_item"].gbrain_symbols
    assert ["Add item", "Title", "Save", "Saved"] == by_name["create_item"].hints
    assert any(
        hit.startswith("code-def CreateItemScreen")
        for hit in by_name["create_item"].gbrain_evidence
    )


def test_extract_flows_fails_without_gbrain(monkeypatch):
    def broken_gbrain(*args):
        raise FileNotFoundError("no gbrain")

    monkeypatch.setattr(flow_extractor, "_gbrain", broken_gbrain)

    with pytest.raises(GBrainUnavailable):
        extract_flows("DemoApp")


def test_extract_flows_local_fallback_is_explicit(monkeypatch):
    def broken_gbrain(*args):
        raise FileNotFoundError("no gbrain")

    monkeypatch.setattr(flow_extractor, "_gbrain", broken_gbrain)

    flows = extract_flows("DemoApp", allow_local_fallback=True)
    assert any("LOCAL_FALLBACK" in hit for hit in flows[0].gbrain_evidence)


def test_expensify_style_expo_routes_become_flow_specs(monkeypatch, tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "index.tsx").write_text(
        'export default function Index() { return <Text>Today</Text>; }\n'
        'router.push("/settings"); parseEntryWithAI("coffee 5");\n',
        encoding="utf-8",
    )
    (app / "settings.tsx").write_text(
        'export default function Settings() { return <Text>Settings</Text>; }\n'
        'const x = "Export"; clearAllData();\n',
        encoding="utf-8",
    )
    (app / "auth.tsx").write_text(
        'export default function AuthScreen() { return <Text>Phone number</Text>; }\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(flow_extractor, "_gbrain", lambda *args: f"hit {args[1] if len(args) > 1 else ''}")

    flows = extract_flows(str(tmp_path))
    by_name = {flow.flow: flow for flow in flows}

    assert {"home_dashboard", "settings", "auth", "create_expense", "clear_data"} <= set(by_name)
    assert by_name["settings"].route == "/settings"
    assert by_name["settings"].source_file == "app/settings.tsx"
    assert by_name["create_expense"].kind == "feature"


def test_try_gbrain_preserves_partial_output_on_timeout(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=["gbrain", "query"],
            timeout=1,
            output="[0.83] app-auth-tsx -- AuthForm",
        )

    monkeypatch.setattr(flow_extractor.subprocess, "run", timeout)

    output, error = flow_extractor._try_gbrain("query", "auth")

    assert "AuthForm" in output
    assert "partial output" in error
