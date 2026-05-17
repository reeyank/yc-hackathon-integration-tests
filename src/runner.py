"""Custom trace-replay runner — the PRIMARY demo path (T6).

Locked (amendment): the runner replays a recorded Trace through idb, checks
real UI state via describe-all, and SHOWS each assertion (element, expected,
actual). It is the differentiator AND the live demo. It must display its
assertions — a self-reported "PASS" tally is the credibility trap we
explicitly rejected.

Demo timing (Issue 7): replay a pre-recorded trace, not a live LLM loop.
Deterministic, fast, zero stage latency.
"""

from __future__ import annotations

from dataclasses import dataclass

from idb_wrapper import IdbWrapper
from trace import Assertion, Trace


@dataclass
class AssertionResult:
    selector: str
    kind: str
    expected: object
    actual: object
    passed: bool


def replay(trace: Trace, idb: IdbWrapper) -> list[AssertionResult]:
    """Replay every flow's steps, evaluate each assertion against the live
    a11y tree, and return per-assertion results. The caller renders these
    visibly (coverage map + console) — that visible verification is the
    point."""
    results: list[AssertionResult] = []
    for flow in trace.flows:
        for step in flow.steps:
            tree = idb.act(step)
            for assertion in step.assertions:
                results.append(check(assertion, tree))
    return results


def check(assertion: Assertion, tree: dict) -> AssertionResult:
    """Evaluate one assertion against a describe-all tree. Real check, real
    actual value — never fabricate the result."""
    node = _find_by_selector(tree, assertion.selector)
    actual = _actual(node)

    if assertion.kind == "exists":
        passed = node is not None
        actual_value: object = "exists" if node else "missing"
    elif assertion.kind == "absent":
        passed = node is None
        actual_value = "missing" if node is None else "exists"
    elif assertion.kind == "value_equals":
        actual_value = actual
        passed = actual == assertion.expected
    elif assertion.kind == "text_contains":
        actual_value = actual
        passed = assertion.expected is not None and str(assertion.expected) in str(actual)
    else:
        raise ValueError(f"unsupported assertion kind {assertion.kind!r}")

    return AssertionResult(
        selector=assertion.selector,
        kind=assertion.kind,
        expected=assertion.expected,
        actual=actual_value,
        passed=passed,
    )


def _find_by_selector(tree: dict, selector: str) -> dict | None:
    for node in _walk(tree):
        values = (
            "identifier",
            "accessibilityIdentifier",
            "AXIdentifier",
            "AXUniqueId",
            "testID",
            "id",
            "label",
            "accessibilityLabel",
            "AXLabel",
            "name",
            "text",
            "title",
        )
        if any(str(node.get(name, "")) == selector for name in values):
            return node
    return None


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


def _actual(node: dict | None) -> object:
    if node is None:
        return None
    for key in (
        "value",
        "AXValue",
        "text",
        "label",
        "accessibilityLabel",
        "AXLabel",
        "name",
        "title",
    ):
        if key in node:
            return node[key]
    return "exists"
