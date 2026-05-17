"""OpenAI + gbrain backed agent runner."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from agent_tui import AgentTUI
from ai_decider import AgentDecision, OpenAIConfigurationError, OpenAIDecider
from explorer import _find_hint
from flow_extractor import GBrainUnavailable, _try_gbrain, extract_flows
from idb_wrapper import FlowAborted, IdbWrapper
from live_proxy import LiveProxyCapture, LiveProxyUnavailable
from network_capture import load_network_events, summarize
from run_report import build_run_report, visual_review
from trace import Action, Assertion, Flow, Step, Target, Trace


AUTH_PHONE_HINTS = ("Phone number", "Continue with phone", "Send code")
AUTH_CODE_HINTS = ("Verification code", "Verify and continue", "Enter the code")
DEFAULT_AGENT_CYCLES = 250


def run_agent(
    app_path: str,
    udid: str,
    bundle_id: str,
    trace_dir: str,
    out: str,
    proxy_log: str | None = None,
    live_proxy: bool = False,
    live_proxy_port: int = 9090,
    live_proxy_out: str | None = None,
    live_proxy_binary: str | None = None,
    allow_local_fallback: bool = False,
    model: str | None = None,
) -> int:
    tui = AgentTUI()
    tui.header(
        "GBRAIN AI Integration Tester",
        f"repo={app_path} bundle={bundle_id}",
    )

    tasks = {
        "gbrain": tui.add_task("Collect gbrain-backed source plan"),
        "network": tui.add_task("Load proxy/network evidence"),
        "openai": tui.add_task("Ask OpenAI for the next testing plan"),
        "sim": tui.add_task("Drive simulator and record trace"),
        "write": tui.add_task("Write deterministic trace artifact"),
    }

    try:
        tui.update_task(tasks["gbrain"], "running", "extracting source symbols and evidence")
        specs = extract_flows(app_path, allow_local_fallback=allow_local_fallback)
        extra_gbrain = _gbrain_context()
        tui.gbrain(_gbrain_rows(specs, extra_gbrain))
        tui.update_task(tasks["gbrain"], "done", f"{len(specs)} flow(s), {len(extra_gbrain)} extra hit(s)")
    except GBrainUnavailable as e:
        tui.update_task(tasks["gbrain"], "blocked", str(e))
        tui.stop()
        return 2

    live_capture: LiveProxyCapture | None = None
    if live_proxy:
        capture_out = live_proxy_out or proxy_log or str(Path(trace_dir) / "network.jsonl")
        live_capture = LiveProxyCapture(
            capture_out,
            port=live_proxy_port,
            binary=live_proxy_binary,
        )
        proxy_log = capture_out
        tui.update_task(tasks["network"], "running", f"starting live proxy on {live_capture.proxy_url}")
        try:
            live_capture.start()
        except LiveProxyUnavailable as e:
            tui.update_task(tasks["network"], "blocked", str(e))
            tui.stop()
            return 2
        tui.log("live_proxy", f"capturing to {capture_out} via {live_capture.proxy_url}")

    tui.update_task(tasks["network"], "running", proxy_log or "no proxy log passed")
    try:
        events = _network_events(proxy_log, live_capture)
    except OSError as e:
        tui.update_task(tasks["network"], "blocked", str(e))
        if live_capture:
            live_capture.stop()
        tui.stop()
        return 2
    network_summary = summarize(events)
    tui.network([event.compact() for event in events])
    tui.update_task(tasks["network"], "done", f"{network_summary['count']} event(s), {network_summary['failures']} failure(s)")

    idb = IdbWrapper(udid, trace_dir, bundle_id=bundle_id)
    trace = Trace(app_path=app_path)
    primary_spec = specs[0] if specs else None
    flow = Flow(
        name=primary_spec.flow if primary_spec else "openai_gbrain_agent_run",
        gbrain_symbols=primary_spec.gbrain_symbols if primary_spec else [],
        gbrain_evidence=(primary_spec.gbrain_evidence if primary_spec else []) + extra_gbrain,
        route=primary_spec.route if primary_spec else None,
        source_file=primary_spec.source_file if primary_spec else None,
        kind=primary_spec.kind if primary_spec else "flow",
    )
    trace.flows.append(flow)
    for spec in specs[1:]:
        trace.flows.append(
            Flow(
                name=spec.flow,
                gbrain_symbols=spec.gbrain_symbols,
                gbrain_evidence=spec.gbrain_evidence,
                status="pending",
                failure="discovered by gbrain/source map but not executed in this run",
                route=spec.route,
                source_file=spec.source_file,
                kind=spec.kind,
            )
        )
    tool_history: list[dict[str, object]] = []
    user_inputs: dict[str, str] = {}

    try:
        tui.update_task(tasks["sim"], "running", "launching app")
        _record(flow, idb, Step(action=Action.LAUNCH))
        tree, _ = idb.observe()

        decider = OpenAIDecider(model=model)
        stopped = False
        exhausted = False
        cycles = int(os.environ.get("IOS_TEST_AGENT_CYCLES", str(DEFAULT_AGENT_CYCLES)))
        for cycle in range(cycles):
            events = _network_events(proxy_log, live_capture)
            network_summary = summarize(events)
            tui.network([event.compact() for event in events])
            tui.update_task(
                tasks["network"],
                "done",
                f"{network_summary['count']} event(s), {network_summary['failures']} failure(s)",
            )
            context = _context(
                app_path,
                specs,
                extra_gbrain,
                tree,
                network_summary,
                tool_history,
            )
            tui.update_task(tasks["openai"], "running", f"planning cycle {cycle + 1}/{cycles}")
            decision = decider.decide(context)
            tui.decision(
                decision.summary,
                decision.risks,
                [f"{call.name}: {call.reason}" for call in decision.tool_calls],
            )
            tui.update_task(
                tasks["openai"],
                "done",
                f"cycle={cycle + 1} confidence={decision.confidence:.2f}",
            )
            result = _execute_tool_calls(
                decision,
                tui,
                flow,
                idb,
                tree,
                lambda: _network_events(proxy_log, live_capture),
                tool_history,
                user_inputs,
            )
            tree = result["tree"]
            stopped = bool(result["stopped"])
            if stopped:
                break
        else:
            exhausted = True

        if not stopped and _looks_like_phone_auth(tree):
            tui.log("fallback", "phone auth detected; using deterministic auth helper")
            _complete_phone_auth(tui, flow, idb)
            stopped = True
        elif not stopped and len(flow.steps) <= 1:
            tui.log("fallback", "no agent action recorded; using gbrain source hints")
            _run_source_hints(flow, specs, idb)
            stopped = True

        if exhausted and not stopped:
            flow.status = "blocked"
            flow.failure = (
                f"max planning cycles reached ({cycles}) before the agent called stop; "
                "run again with IOS_TEST_AGENT_CYCLES set higher for long onboarding"
            )
            tui.update_task(tasks["sim"], "blocked", flow.failure)
        else:
            flow.status = "passed"
            tui.update_task(tasks["sim"], "done", f"{len(flow.steps)} step(s) recorded")
    except OpenAIConfigurationError as e:
        flow.status = "blocked"
        flow.failure = str(e)
        tui.update_task(tasks["openai"], "blocked", str(e))
        return 2
    except FlowAborted as e:
        flow.status = "failed"
        flow.failure = str(e)
        tui.update_task(tasks["sim"], "blocked", str(e))
        return 1
    finally:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(trace.to_json(), encoding="utf-8")
        final_events = []
        if live_capture:
            final_events = live_capture.events()
            tui.network([event.compact() for event in final_events])
            tui.update_task(tasks["network"], "done", f"{len(final_events)} captured event(s)")
            live_capture.stop()
        else:
            try:
                final_events = _network_events(proxy_log, live_capture)
            except OSError:
                final_events = []
        tui.update_task(tasks["write"], "running", "reviewing screenshots and writing report")
        notes = visual_review(trace, trace_dir, model=model)
        report = build_run_report(
            trace=trace,
            trace_dir=trace_dir,
            network_events=final_events,
            tool_history=tool_history,
            visual_notes=notes,
            trace_path=out_path,
        )
        report_path = out_path.with_suffix(".report.md")
        report_path.write_text(report, encoding="utf-8")
        tui.update_task(tasks["write"], "done", f"{out_path} + {report_path}")
        tui.final_report(report)

    return 1 if any(flow.status in {"failed", "blocked"} for flow in trace.flows) else 0


def _context(
    app_path: str,
    specs: list[Any],
    extra_gbrain: list[str],
    tree: dict,
    network_summary: dict[str, object],
    tool_history: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "app_path": app_path,
        "gbrain_flows": [
            {
                "flow": spec.flow,
                "symbols": spec.gbrain_symbols,
                "hints": spec.hints,
                "evidence": spec.gbrain_evidence,
            }
            for spec in specs
        ],
        "gbrain_search": extra_gbrain,
        "visible_ui": _visible_strings(tree)[:80],
        "network": network_summary,
        "tool_history": tool_history or [],
        "available_tools": [
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
    }


def _gbrain_rows(specs: list[Any], extra_gbrain: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for spec in specs:
        evidence = spec.gbrain_evidence[0] if spec.gbrain_evidence else ""
        symbols = spec.gbrain_symbols or [""]
        for symbol in symbols[:3]:
            rows.append(
                {
                    "flow": str(spec.flow),
                    "symbol": str(symbol),
                    "evidence": evidence,
                }
            )
    for hit in extra_gbrain[:3]:
        rows.append({"flow": "context", "symbol": "hybrid-query", "evidence": hit})
    return rows


def _execute_tool_calls(
    decision: AgentDecision,
    tui: AgentTUI,
    flow: Flow,
    idb: IdbWrapper,
    tree: dict,
    network_events_factory,
    tool_history: list[dict[str, object]],
    user_inputs: dict[str, str],
) -> dict[str, object]:
    acted = False
    stopped = False
    current_tree = tree
    if not decision.tool_calls:
        tool_history.append({"tool": "plan", "status": "done", "result": "no tool calls"})
        return {"tree": current_tree, "acted": acted, "stopped": stopped}

    for call in decision.tool_calls:
        name = call.name
        args = call.arguments
        try:
            if name == "observe_ui":
                current_tree, _ = idb.observe()
                result = f"{len(_visible_strings(current_tree))} visible string(s)"
                tui.log("observe_ui", result)

            elif name == "tap":
                target = _target_from_args(current_tree, args)
                if target is None:
                    raise FlowAborted(f"tap target not found for {args}")
                _record(flow, idb, Step(action=Action.TAP, target=target))
                current_tree, _ = idb.observe()
                result = _target_summary(target)
                acted = True
                tui.log("tap", result)

            elif name == "type_text":
                target = _target_from_args(current_tree, args) or _first_text_input(current_tree)
                if target is None:
                    raise FlowAborted(f"type_text target not found for {args}")
                value = _text_value(tui, args, user_inputs)
                _record(flow, idb, Step(action=Action.TYPE, target=target, value=value))
                current_tree, _ = idb.observe()
                result = f"{_target_summary(target)} value={_redact_value(args, value)}"
                acted = True
                tui.log("type_text", result)

            elif name == "swipe":
                target = _target_from_args(current_tree, args) or _screen_target(current_tree)
                direction = str(args.get("direction") or "up")
                _record(flow, idb, Step(action=Action.SWIPE, target=target, value=direction))
                current_tree, _ = idb.observe()
                result = direction
                acted = True
                tui.log("swipe", result)

            elif name == "ask_user":
                field = str(args.get("field") or "value")
                prompt = str(args.get("prompt") or field.replace("_", " ").title())
                answer = tui.ask(prompt, password=_is_secret_field(field))
                user_inputs[field] = answer
                result = f"captured {field}"
                tui.log("ask_user", result)

            elif name == "query_gbrain":
                query = str(args.get("query") or args.get("selector") or decision.summary)
                output, error = _try_gbrain("query", query, "--no-expand")
                result = (output or error or "no gbrain result").strip()[:700]
                flow.gbrain_evidence.append(f"agent-query {query!r}: {result}")
                tui.log("query_gbrain", result)

            elif name == "inspect_network":
                network_summary = summarize(network_events_factory())
                result = json.dumps(network_summary, sort_keys=True)[:700]
                tui.log("inspect_network", result)

            elif name == "assert_visible":
                selector = _arg_first(args, "selector", "expected", "text", "field")
                if not selector:
                    raise FlowAborted("assert_visible requires selector or expected text")
                if not _find_hint(current_tree, selector):
                    raise FlowAborted(f"assert_visible failed: {selector!r} was not visible")
                if flow.steps:
                    flow.steps[-1].assertions.append(Assertion(kind="exists", selector=selector))
                result = f"visible: {selector}"
                tui.log("assert_visible", result)

            elif name == "stop":
                result = call.reason or "agent stopped"
                stopped = True
                tui.log("stop", result)

            else:
                result = f"unsupported tool {name}"
                tui.log("tool", result)

            tool_history.append({"tool": name, "status": "done", "result": result})
        except FlowAborted:
            raise
        except Exception as e:
            detail = f"{type(e).__name__}: {e}"
            tool_history.append({"tool": name, "status": "failed", "result": detail})
            tui.log(name, detail)
            raise FlowAborted(detail) from e
        if stopped:
            break

    return {"tree": current_tree, "acted": acted, "stopped": stopped}


def _network_events(proxy_log: str | None, live_capture: LiveProxyCapture | None):
    if live_capture:
        return live_capture.events()
    return load_network_events(proxy_log)


def _complete_phone_auth(tui: AgentTUI, flow: Flow, idb: IdbWrapper) -> None:
    phone = tui.ask("Phone number")
    tree, _ = idb.observe()
    target = _first_text_input(tree) or _target_for_first(tree, ("Phone number", "Continue with phone"))
    if target is None:
        raise FlowAborted("phone auth visible but no phone input target was found")
    _record(flow, idb, Step(action=Action.TYPE, target=target, value=phone))

    tree, _ = idb.observe()
    send = _target_for_first(tree, ("Send code", "Continue with phone"))
    if send is None:
        raise FlowAborted("phone number entered but send-code button was not found")
    _record(flow, idb, Step(action=Action.TAP, target=send))

    otp = tui.ask("OTP code", password=True)
    tree = _wait_for_any(idb, AUTH_CODE_HINTS, timeout_s=20)
    code_target = _first_text_input(tree) or _target_for_first(tree, AUTH_CODE_HINTS)
    if code_target is None:
        raise FlowAborted("OTP screen visible but no code input target was found")
    _record(flow, idb, Step(action=Action.TYPE, target=code_target, value=otp))

    tree, _ = idb.observe()
    verify = _target_for_first(tree, ("Verify and continue", "Continue"))
    if verify is None:
        raise FlowAborted("OTP entered but verify button was not found")
    _record(
        flow,
        idb,
        Step(
            action=Action.TAP,
            target=verify,
            assertions=[Assertion(kind="absent", selector="Verify and continue")],
        ),
    )


def _target_from_args(tree: dict, args: dict[str, Any]) -> Target | None:
    selector = _arg_first(args, "selector", "field", "expected", "text")
    if not selector:
        return None
    node = _find_hint(tree, selector)
    if not node:
        return None
    return Target(
        a11y_id=_first(node, "AXUniqueId", "AXIdentifier", "accessibilityIdentifier", "testID", "id"),
        label=_first(node, "AXLabel", "accessibilityLabel", "label", "name"),
        text=_first(node, "text", "title", "AXValue", "value"),
        coord=_center_or_none(node),
    )


def _screen_target(tree: dict) -> Target:
    for node in _walk(tree):
        coord = _center_or_none(node)
        if coord:
            return Target(coord=coord)
    return Target(coord=(200.0, 400.0))


def _arg_first(args: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = args.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _text_value(tui: AgentTUI, args: dict[str, Any], user_inputs: dict[str, str]) -> str:
    field = _arg_first(args, "field") or "value"
    value = _arg_first(args, "text")
    if value and value.startswith("$"):
        value = user_inputs.get(value[1:])
    if not value:
        value = user_inputs.get(field)
    if not value:
        prompt = _arg_first(args, "prompt") or field.replace("_", " ").title()
        value = tui.ask(prompt, password=_is_secret_field(field))
        user_inputs[field] = value
    return value


def _is_secret_field(field: str) -> bool:
    lowered = field.lower()
    return any(secret in lowered for secret in ("otp", "code", "password", "token", "secret"))


def _redact_value(args: dict[str, Any], value: str) -> str:
    field = _arg_first(args, "field") or ""
    if _is_secret_field(field):
        return "[hidden]"
    if len(value) > 24:
        return value[:21] + "..."
    return value


def _target_summary(target: Target) -> str:
    return (
        target.a11y_id
        or target.label
        or target.text
        or (f"coord={target.coord}" if target.coord else "unknown target")
    )


def _run_source_hints(flow: Flow, specs: list[Any], idb: IdbWrapper) -> None:
    for spec in specs[:1]:
        for hint in spec.hints[:4]:
            tree = _wait_for_any(idb, (hint,), timeout_s=4)
            target = _target_for_first(tree, (hint,))
            if target is not None:
                _record(flow, idb, Step(action=Action.TAP, target=target))


def _record(flow: Flow, idb: IdbWrapper, step: Step) -> None:
    tree = idb.act(step)
    tree, screenshot = idb.observe()
    step.screenshot = Path(screenshot).name
    step.ui_tree_hash = str(abs(hash(json.dumps(tree, sort_keys=True, default=str))))[:12]
    flow.steps.append(step)


def _wait_for_any(idb: IdbWrapper, hints: tuple[str, ...], timeout_s: float) -> dict:
    deadline = time.monotonic() + timeout_s
    last: dict | None = None
    while time.monotonic() < deadline:
        tree, _ = idb.observe()
        last = tree
        if any(_find_hint(tree, hint) for hint in hints):
            return tree
        time.sleep(0.4)
    if last is None:
        raise FlowAborted(f"could not observe UI while waiting for {hints}")
    return last


def _looks_like_phone_auth(tree: dict) -> bool:
    visible = " ".join(_visible_strings(tree)).lower()
    return any(hint.lower() in visible for hint in AUTH_PHONE_HINTS)


def _target_for_first(tree: dict, hints: tuple[str, ...]) -> Target | None:
    for hint in hints:
        node = _find_hint(tree, hint)
        if node:
            return Target(
                a11y_id=_first(node, "AXUniqueId", "AXIdentifier", "accessibilityIdentifier", "testID", "id"),
                label=_first(node, "AXLabel", "accessibilityLabel", "label", "name"),
                text=_first(node, "text", "title", "AXValue", "value"),
                coord=_center_or_none(node),
            )
    return None


def _first_text_input(tree: dict) -> Target | None:
    for node in _walk(tree):
        text = _node_text(node).lower()
        kind = str(node.get("type") or node.get("role") or "").lower()
        if "textfield" in text or "textfield" in kind or "textinput" in kind:
            return Target(
                label=_first(node, "AXLabel", "accessibilityLabel", "label", "name"),
                text=_first(node, "text", "title", "AXValue", "value"),
                coord=_center_or_none(node),
            )
    return None


def _gbrain_context() -> list[str]:
    hits: list[str] = []
    for question in (
        "authentication flow phone otp react native",
        "network requests backend api parse expense",
        "navigation between screens",
    ):
        output, error = _try_gbrain("query", question, "--no-expand")
        if output.strip():
            hits.append(f"hybrid-query {question!r}: {output.strip()[:500]}")
        elif error:
            hits.append(f"hybrid-query {question!r}: {error}")
    return hits


def _visible_strings(tree: dict) -> list[str]:
    values: list[str] = []
    for node in _walk(tree):
        text = _node_text(node)
        if text and text not in values:
            values.append(text)
    return values


def _walk(node) -> list[dict]:
    found: list[dict] = []
    if isinstance(node, dict):
        found.append(node)
        for key in ("children", "subviews", "elements"):
            for child in node.get(key, []) or []:
                found.extend(_walk(child))
    elif isinstance(node, list):
        for child in node:
            found.extend(_walk(child))
    return found


def _node_text(node: dict) -> str:
    keys = (
        "AXUniqueId",
        "AXIdentifier",
        "accessibilityIdentifier",
        "testID",
        "AXLabel",
        "accessibilityLabel",
        "label",
        "name",
        "text",
        "title",
        "AXValue",
        "value",
    )
    return " ".join(str(node.get(key)) for key in keys if node.get(key) not in (None, ""))


def _first(node: dict, *keys: str) -> str | None:
    for key in keys:
        value = node.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _center_or_none(node: dict) -> tuple[float, float] | None:
    frame = node.get("frame") or node.get("rect") or node.get("bounds")
    if not isinstance(frame, dict):
        return None
    if "origin" in frame and "size" in frame:
        origin = frame["origin"]
        size = frame["size"]
        return (
            float(origin["x"]) + float(size["width"]) / 2,
            float(origin["y"]) + float(size["height"]) / 2,
        )
    return (
        float(frame.get("x", 0)) + float(frame.get("width", 0)) / 2,
        float(frame.get("y", 0)) + float(frame.get("height", 0)) / 2,
    )
