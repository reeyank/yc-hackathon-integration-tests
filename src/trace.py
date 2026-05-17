"""Trace schema — THE contract.

Locked by /plan-eng-review (Issue 2): flow-grouped step list. This module is
the single shared definition read/written by every other component:

    flow_extractor  ─┐
    explorer        ─┼─►  Trace  ─┬─►  runner       (primary demo, T6)
                                  ├─►  codegen_detox (proof artifact, T6)
                                  └─►  coverage map  (the demo screen, T8)

Selector fallback order (locked): a11y_id -> label -> visible text -> coordinate.
Generate tests from a recorded Trace, never from agent memory — this is what
makes the demo deterministic while exploration looks autonomous.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


SCHEMA_VERSION = 1


class Action(str, Enum):
    LAUNCH = "launch"
    TAP = "tap"
    TYPE = "type"
    SWIPE = "swipe"
    BACK = "back"


@dataclass
class Target:
    """How to locate an element. At least one field set; resolution tries them
    in order: a11y_id, then label, then text, then coord. `resolved_by` records
    which one actually worked at record time (drives selector hardening / the
    auto-patch decision in source_patcher)."""

    a11y_id: str | None = None
    label: str | None = None
    text: str | None = None
    coord: tuple[float, float] | None = None
    resolved_by: str | None = None  # "a11y_id" | "label" | "text" | "coord"

    def is_stable(self) -> bool:
        """A stable target survives layout shifts. Only a11y_id qualifies;
        coord-resolved targets are the ones source_patcher offers to harden."""
        return self.resolved_by == "a11y_id"


@dataclass
class Assertion:
    """A real, observable post-condition checked against the live a11y tree.
    The runner SHOWS each of these (element, expected, actual) so the demo is
    verifiably testing, not self-reporting a tally."""

    kind: str  # "exists" | "absent" | "value_equals" | "text_contains"
    selector: str  # a11y_id or label of the element under assertion
    expected: Any = None


@dataclass
class Step:
    action: Action
    target: Target | None = None  # None only for LAUNCH / BACK
    value: str | None = None  # text for TYPE; swipe direction for SWIPE
    screenshot: str | None = None  # filename relative to the trace dir
    ui_tree_hash: str | None = None  # settle-detection + retry/repair key
    assertions: list[Assertion] = field(default_factory=list)


@dataclass
class Flow:
    """One user flow -> one generated test function. gbrain_symbols is the
    provenance: the Swift/TSX symbols this flow exercises, from flow_extractor.
    gbrain_evidence records the actual gbrain query hits that justified this
    flow. status records exploration outcome for the findings report."""

    name: str
    gbrain_symbols: list[str] = field(default_factory=list)
    gbrain_evidence: list[str] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    status: str = "pending"  # pending | passed | failed | blocked
    failure: str | None = None  # why it failed/blocked (-> fix-prompt input)
    route: str | None = None
    source_file: str | None = None
    kind: str = "flow"


@dataclass
class Trace:
    schema_version: int = SCHEMA_VERSION
    app_path: str = ""
    flows: list[Flow] = field(default_factory=list)

    # --- serialization: the on-disk contract -------------------------------

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(asdict(self), indent=indent, default=_enc)

    def save(self, path: str) -> None:
        with open(path, "w") as fh:
            fh.write(self.to_json())

    @staticmethod
    def load(path: str) -> "Trace":
        with open(path) as fh:
            return Trace.from_dict(json.load(fh))

    @staticmethod
    def from_dict(d: dict) -> "Trace":
        if d.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"trace schema {d.get('schema_version')} != {SCHEMA_VERSION}; "
                "migrate before consuming"
            )
        flows = []
        for f in d.get("flows", []):
            steps = []
            for s in f.get("steps", []):
                tgt = s.get("target")
                if tgt and tgt.get("coord") is not None:
                    tgt = {**tgt, "coord": tuple(tgt["coord"])}
                steps.append(
                    Step(
                        action=Action(s["action"]),
                        target=Target(**tgt) if tgt else None,
                        value=s.get("value"),
                        screenshot=s.get("screenshot"),
                        ui_tree_hash=s.get("ui_tree_hash"),
                        assertions=[Assertion(**a) for a in s.get("assertions", [])],
                    )
                )
            flows.append(
                Flow(
                    name=f["name"],
                    gbrain_symbols=f.get("gbrain_symbols", []),
                    gbrain_evidence=f.get("gbrain_evidence", []),
                    steps=steps,
                    status=f.get("status", "pending"),
                    failure=f.get("failure"),
                    route=f.get("route"),
                    source_file=f.get("source_file"),
                    kind=f.get("kind", "flow"),
                )
            )
        return Trace(
            schema_version=d["schema_version"],
            app_path=d.get("app_path", ""),
            flows=flows,
        )


def _enc(o: Any) -> Any:
    if isinstance(o, Action):
        return o.value
    if isinstance(o, tuple):
        return list(o)
    raise TypeError(f"not JSON-serializable: {type(o)}")
