"""Directed traversal explorer (T5).

Approach B (locked): NOT open-ended discovery. gbrain hands the flow list +
hints; the agent navigates toward known targets and records a deterministic
flow-grouped Trace. Looks autonomous (no human wrote a test plan); is
reliable because it's goal-seeking, not wandering.

Loop per step:  observe() -> pick element matching the flow hint ->
act() -> record Step (+ assertion) -> repeat until flow goal or FlowAborted.
On FlowAborted: mark Flow status=failed/blocked with the reason (feeds the
findings report + fix-prompts).
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from flow_extractor import FlowSpec
from idb_wrapper import FlowAborted, IdbWrapper
from trace import Action, Assertion, Flow, Step, Target, Trace


def explore(app_path: str, specs: list[FlowSpec], idb: IdbWrapper) -> Trace:
    trace = Trace(app_path=app_path)
    for index, spec in enumerate(specs):
        flow = Flow(
            name=spec.flow,
            gbrain_symbols=spec.gbrain_symbols,
            gbrain_evidence=spec.gbrain_evidence,
            route=spec.route,
            source_file=spec.source_file,
            kind=spec.kind,
        )
        try:
            if index == 0 and idb.bundle_id:
                _record(flow, Step(action=Action.LAUNCH), idb)
            _run_flow(flow, spec, idb)
            flow.status = "passed"
        except FlowAborted as e:
            flow.status = "failed"
            flow.failure = str(e)  # -> findings report / fix-prompt
        trace.flows.append(flow)
    return trace


def _run_flow(flow: Flow, spec: FlowSpec, idb: IdbWrapper) -> None:
    """Goal-conditioned navigation toward spec.hints. Records each Step with
    its assertion. Never writes a partial step (idb_wrapper.act raises before
    a bad step is appended)."""
    for hint in spec.hints:
        tree = _observe_until_hint(idb, hint)

        if _is_terminal_hint(hint, tree):
            if flow.steps:
                _attach_assertion(flow, Assertion(kind="exists", selector=_selector_for_hint(hint)))
            continue

        node = _find_hint(tree, hint)
        if not node:
            raise FlowAborted(f"hint not found: {hint}")

        target = _target_from_node(node)
        if _is_text_input(node, hint):
            step = Step(
                action=Action.TYPE,
                target=target,
                value=_value_for_hint(hint),
                assertions=_post_assertions(hint),
            )
        else:
            step = Step(
                action=Action.TAP,
                target=target,
                assertions=_post_assertions(hint),
            )
        _record(flow, step, idb)


def _record(flow: Flow, step: Step, idb: IdbWrapper) -> None:
    tree = idb.act(step)
    if step.assertions:
        tree = _wait_assertions(idb, step.assertions)
    tree, screenshot = idb.observe()
    step.screenshot = Path(screenshot).name
    step.ui_tree_hash = _hash_tree(tree)
    flow.steps.append(step)


def _attach_assertion(flow: Flow, assertion: Assertion) -> None:
    if not flow.steps:
        raise FlowAborted(f"cannot attach assertion without a recorded step: {assertion}")
    if any(
        existing.kind == assertion.kind and existing.selector == assertion.selector
        for existing in flow.steps[-1].assertions
    ):
        return
    flow.steps[-1].assertions.append(assertion)


def _find_hint(tree: dict, hint: str) -> dict | None:
    nodes = _walk(tree)
    exact = [node for node in nodes if _node_text(node) == hint]
    if exact:
        return _best_node(exact)
    partial = [node for node in nodes if hint.lower() in _node_text(node).lower()]
    if partial:
        return _best_node(partial)
    return None


def _observe_until_hint(idb: IdbWrapper, hint: str, timeout_s: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout_s
    last_tree: dict | None = None
    while time.monotonic() < deadline:
        tree, _ = idb.observe()
        last_tree = tree
        if _find_hint(tree, hint):
            return tree
        time.sleep(0.25)
    if last_tree is None:
        raise FlowAborted(f"could not observe tree while waiting for hint: {hint}")
    return last_tree


def _wait_assertions(
    idb: IdbWrapper, assertions: list[Assertion], timeout_s: float = 3.0
) -> dict:
    deadline = time.monotonic() + timeout_s
    last_tree: dict | None = None
    while time.monotonic() < deadline:
        tree, _ = idb.observe()
        last_tree = tree
        if all(_assertion_visible(tree, assertion) for assertion in assertions):
            return tree
        time.sleep(0.25)
    if last_tree is None:
        raise FlowAborted("could not observe tree while waiting for assertions")
    missing = [a.selector for a in assertions if not _assertion_visible(last_tree, a)]
    raise FlowAborted(f"post-action assertion not visible: {missing}")


def _assertion_visible(tree: dict, assertion: Assertion) -> bool:
    if assertion.kind == "absent":
        return _find_hint(tree, assertion.selector) is None
    return _find_hint(tree, assertion.selector) is not None


def _best_node(nodes: list[dict]) -> dict:
    actionable = [node for node in nodes if _looks_actionable(node)]
    framed = [node for node in actionable if _has_frame(node)]
    if framed:
        return framed[0]
    framed = [node for node in nodes if _has_frame(node)]
    if framed:
        return framed[0]
    return nodes[0]


def _looks_actionable(node: dict) -> bool:
    role = str(node.get("role") or node.get("type") or node.get("role_description") or "")
    return any(token in role.lower() for token in ("button", "generic", "textfield", "textinput"))


def _has_frame(node: dict) -> bool:
    return isinstance(node.get("frame") or node.get("rect") or node.get("bounds"), dict)


def _target_from_node(node: dict) -> Target:
    return Target(
        a11y_id=_first(node, "AXUniqueId", "AXIdentifier", "accessibilityIdentifier", "testID", "id"),
        label=_first(node, "AXLabel", "accessibilityLabel", "label", "name"),
        text=_first(node, "text", "title", "AXValue", "value"),
    )


def _first(node: dict, *keys: str) -> str | None:
    for key in keys:
        value = node.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _node_text(node: dict) -> str:
    values = [
        node.get("AXUniqueId"),
        node.get("AXIdentifier"),
        node.get("accessibilityIdentifier"),
        node.get("testID"),
        node.get("AXLabel"),
        node.get("accessibilityLabel"),
        node.get("label"),
        node.get("name"),
        node.get("text"),
        node.get("title"),
        node.get("AXValue"),
        node.get("value"),
    ]
    return " ".join(str(value) for value in values if value not in (None, ""))


def _is_text_input(node: dict, hint: str) -> bool:
    role = _node_text(node).lower() + " " + str(node.get("type") or "").lower()
    return hint.lower() in {"title", "name", "email"} or "textfield" in role


def _value_for_hint(hint: str) -> str:
    if hint.lower() == "title":
        return "Hackathon trace"
    return f"gbrain {hint.lower()}"


def _post_assertions(hint: str) -> list[Assertion]:
    selector = {
        "Continue": "Items",
        "Open": "Back to list",
        "Back to list": "Items",
        "Add item": "Title",
        "Title": "Save",
        "Save": "Saved confirmation",
        "Settings": "Seeded data, local-only mode",
    }.get(hint)
    if not selector:
        return []
    return [Assertion(kind="exists", selector=selector)]


def _is_terminal_hint(hint: str, tree: dict) -> bool:
    if hint not in {"Items", "Saved"}:
        return False
    return _find_hint(tree, hint) is not None


def _selector_for_hint(hint: str) -> str:
    return {
        "Saved": "Saved confirmation",
    }.get(hint, hint)


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


def _hash_tree(tree: dict) -> str:
    return hashlib.sha1(repr(tree).encode()).hexdigest()[:12]
