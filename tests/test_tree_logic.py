import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from idb_wrapper import IdbWrapper  # noqa: E402
from runner import check, replay  # noqa: E402
from trace import Action, Assertion, Flow, Step, Target, Trace  # noqa: E402


TREE = {
    "children": [
        {
            "identifier": "add-item-btn",
            "label": "Add item",
            "frame": {"x": 20, "y": 40, "width": 100, "height": 44},
        },
        {
            "label": "Title",
            "value": "O'Brien",
            "frame": {"origin": {"x": 20, "y": 110}, "size": {"width": 200, "height": 52}},
        },
        {
            "identifier": "toast",
            "label": "Saved",
            "frame": {"x": 20, "y": 200, "width": 120, "height": 30},
        },
    ]
}


def test_resolve_prefers_stable_a11y_id():
    target = Target(a11y_id="add-item-btn", label="Add item")
    assert IdbWrapper.resolve(target, TREE) == (70, 62)
    assert target.resolved_by == "a11y_id"


def test_resolve_falls_back_to_label():
    target = Target(label="Title")
    assert IdbWrapper.resolve(target, TREE) == (120, 136)
    assert target.resolved_by == "label"


def test_check_assertions_against_tree():
    exists = check(Assertion(kind="exists", selector="toast"), TREE)
    contains = check(Assertion(kind="text_contains", selector="toast", expected="Save"), TREE)
    absent = check(Assertion(kind="absent", selector="missing"), TREE)

    assert exists.passed
    assert contains.passed
    assert absent.passed


def test_replay_returns_visible_assertion_results():
    class FakeIdb:
        def act(self, step):
            assert step.action == Action.LAUNCH
            return TREE

    trace = Trace(
        flows=[
            Flow(
                name="smoke",
                steps=[Step(action=Action.LAUNCH, assertions=[Assertion("exists", "toast")])],
            )
        ]
    )

    results = replay(trace, FakeIdb())
    assert len(results) == 1
    assert results[0].selector == "toast"
    assert results[0].passed
