"""End-of-run report generation for the agent TUI."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

from network_capture import NetworkEvent
from trace import Trace


def build_run_report(
    trace: Trace,
    trace_dir: str | Path,
    network_events: list[NetworkEvent],
    tool_history: list[dict[str, object]],
    visual_notes: str,
    trace_path: str | Path,
) -> str:
    trace_root = Path(trace_dir)
    steps = [step for flow in trace.flows for step in flow.steps]
    assertions = [assertion for step in steps for assertion in step.assertions]
    failed_flows = [flow for flow in trace.flows if flow.status in {"failed", "blocked"}]
    pending_flows = [flow for flow in trace.flows if flow.status == "pending"]
    executed_flows = [flow for flow in trace.flows if flow.steps]
    network_failures = [
        event
        for event in network_events
        if event.error or (event.status is not None and event.status >= 400)
    ]

    lines = [
        "# Integration Run Summary",
        "",
        f"Trace: `{trace_path}`",
        f"App: `{trace.app_path}`",
        f"Flows tested: `{len(trace.flows)}`",
        f"Executed flows: `{len(executed_flows)}`",
        f"Untested discovered flows: `{len(pending_flows)}`",
        f"Steps recorded: `{len(steps)}`",
        f"Assertions attached: `{len(assertions)}`",
        f"Network events: `{len(network_events)}` total, `{len(network_failures)}` failing",
        "",
        "## What Ran",
        "",
    ]

    for flow in trace.flows:
        lines.extend(
            [
                f"- `{flow.name}`: `{flow.status}` with `{len(flow.steps)}` step(s)",
                f"  - route/source: `{flow.route or 'unknown'}` / `{flow.source_file or 'unknown'}`",
                f"  - kind: `{flow.kind}`",
                f"  - gbrain symbols: {', '.join(flow.gbrain_symbols) or 'none'}",
            ]
        )
        if flow.failure:
            lines.append(f"  - failure: {flow.failure}")
        for index, step in enumerate(flow.steps, start=1):
            target = step.target
            selector = "app"
            if target:
                selector = target.a11y_id or target.label or target.text or str(target.coord)
            suffix = f" value=`{_redact_value(step.value)}`" if step.value else ""
            lines.append(f"  - {index}. `{step.action.value}` `{selector}`{suffix}")

    lines.extend(["", "## GBrain Backbone", ""])
    if any(flow.gbrain_symbols or flow.gbrain_evidence for flow in trace.flows):
        lines.append(
            "- This run was seeded from gbrain code indexing, and the trace keeps that provenance attached."
        )
        for flow in trace.flows:
            lines.append(f"- `{flow.name}`")
            lines.append(f"  - symbols: {', '.join(flow.gbrain_symbols) or 'none'}")
            for hit in flow.gbrain_evidence[:5]:
                lines.append(f"  - evidence: {hit[:260]}")
    else:
        lines.append("- No gbrain provenance was attached to this trace.")

    lines.extend(["", "## What Broke", ""])
    if failed_flows:
        for flow in failed_flows:
            lines.append(f"- `{flow.name}` ended `{flow.status}`: {flow.failure or 'no detail'}")
    if pending_flows:
        lines.append(f"- `{len(pending_flows)}` discovered flow(s) were not executed in this run:")
        for flow in pending_flows[:12]:
            lines.append(f"  - `{flow.name}` from `{flow.source_file or flow.route or 'unknown'}`")
    if network_failures:
        for event in network_failures[-8:]:
            lines.append(f"- `{event.method}` `{event.url}` returned `{event.status or event.error}`")
    if not failed_flows and not network_failures:
        lines.append("- No hard failure was recorded in the trace or network log.")

    lines.extend(["", "## Network Read", ""])
    if network_events:
        hosts = sorted({event.url.split('/')[2] for event in network_events if '://' in event.url})
        lines.append(f"- Hosts seen: {', '.join(hosts[:8]) or 'none'}")
        lines.append(f"- Recent calls: `{len(network_events[-8:])}` shown in the live TUI.")
    else:
        lines.append("- No network traffic reached the proxy during this run.")
        lines.append("- That usually means the app did not make a request, or the simulator/app was not pointed at the live proxy.")

    screenshots = _screenshots(trace, trace_root)
    lines.extend(["", "## Visual Notes", "", visual_notes])
    if screenshots:
        lines.append("")
        lines.append("Screenshots captured:")
        for shot in screenshots[-6:]:
            lines.append(f"- `{shot}`")

    lines.extend(["", "## Agent Notes", ""])
    if tool_history:
        for entry in tool_history[-10:]:
            lines.append(
                f"- `{entry.get('tool')}` `{entry.get('status')}`: "
                f"{str(entry.get('result', ''))[:220]}"
            )
    else:
        lines.append("- No tool calls were recorded.")

    lines.extend(["", "## What Could Be Better", ""])
    lines.extend(_improvements(trace, network_events, tool_history))
    return "\n".join(lines) + "\n"


def visual_review(trace: Trace, trace_dir: str | Path, model: str | None = None) -> str:
    screenshots = [Path(path) for path in _screenshots(trace, Path(trace_dir))[-3:]]
    if not screenshots:
        return "- No screenshots were attached to the trace, so visual review could not run."
    if not os.environ.get("OPENAI_API_KEY"):
        return (
            f"- Captured `{len(screenshots)}` recent screenshot(s), but OpenAI visual review "
            "was skipped because `OPENAI_API_KEY` is not visible."
        )
    try:
        from openai import OpenAI
    except ModuleNotFoundError:
        return "- OpenAI visual review skipped because the `openai` package is not installed."

    content: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": (
                "Review these iOS simulator screenshots from an autonomous integration "
                "test. Give concise bullets: what screen/flow is visible, anything "
                "broken or suspicious, and one product/testing improvement. Do not "
                "overclaim beyond what is visible."
            ),
        }
    ]
    for screenshot in screenshots:
        content.append(
            {
                "type": "input_image",
                "image_url": _data_url(screenshot),
            }
        )
    try:
        response = OpenAI().responses.create(
            model=model or os.environ.get("IOS_TEST_OPENAI_MODEL", "gpt-5.4"),
            input=[{"role": "user", "content": content}],
            max_output_tokens=500,
        )
    except Exception as e:  # noqa: BLE001 - visual review is best-effort reporting
        return f"- Visual review could not complete: {type(e).__name__}: {e}"
    return response.output_text.strip()


def _screenshots(trace: Trace, trace_dir: Path) -> list[str]:
    found: list[str] = []
    for flow in trace.flows:
        for step in flow.steps:
            if step.screenshot:
                path = trace_dir / step.screenshot
                if path.exists() and str(path) not in found:
                    found.append(str(path))
    return found


def _data_url(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"


def _redact_value(value: str | None) -> str:
    if not value:
        return ""
    if len(value) > 24:
        return value[:21] + "..."
    return value


def _improvements(
    trace: Trace,
    network_events: list[NetworkEvent],
    tool_history: list[dict[str, object]],
) -> list[str]:
    lines: list[str] = []
    if not network_events:
        lines.append("- Make proxy routing automatic for the simulator so backend evidence appears without manual setup.")
    pending = [flow for flow in trace.flows if flow.status == "pending"]
    if pending:
        lines.append("- Add a multi-flow scheduler that resumes from auth/onboarding and executes every discovered pending route.")
    if any("coord=" in str(entry.get("result", "")) for entry in tool_history):
        lines.append("- Add stable accessibility identifiers where the agent fell back to coordinates.")
    if not any(step.assertions for flow in trace.flows for step in flow.steps):
        lines.append("- Add stronger visible assertions so replay proves outcomes, not just navigation.")
    if any(flow.status != "passed" for flow in trace.flows):
        lines.append("- Feed failed flow context back into gbrain as a fix prompt for the next run.")
    if not lines:
        lines.append("- Increase breadth: test more flows and add network-backed assertions for persistence.")
    return lines
