"""idb observe/act/trace wrapper (T3).

Error posture locked by /plan-eng-review (Issue 5): explicit retry + settle,
fail loud. Bounded retry w/ backoff per idb call; after an action, poll
describe-all until ui_tree_hash stabilizes or timeout; on persistent failure
RAISE FlowAborted and never write a partial step to the trace.

Uses the official fb-idb Python client (locked: Python orchestrator, Issue 1).
idb is language-agnostic — works identically on a React Native app.
"""

from __future__ import annotations

import json
import os
import hashlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

from trace import Action, Step, Target


class IdbError(RuntimeError):
    """Transient idb failure (gRPC drop, stale tree, missed tap)."""


class FlowAborted(RuntimeError):
    """Persistent failure after retries. The current flow is abandoned;
    the trace gets NO partial step. Caller marks the flow status=failed."""


RETRIES = 3
SETTLE_TIMEOUT_S = 5.0


def _hash_tree(tree: dict) -> str:
    return hashlib.sha1(repr(tree).encode()).hexdigest()[:12]


class IdbWrapper:
    """Thin, fail-loud wrapper around the idb companion gRPC client.

    observe() -> (a11y_tree, screenshot_path)
    act(step) -> applies the step, waits for settle, returns the new tree
    """

    def __init__(self, udid: str, trace_dir: str, bundle_id: str | None = None) -> None:
        self.udid = udid
        self.trace_dir = trace_dir
        self.bundle_id = bundle_id or os.environ.get("IDB_BUNDLE_ID")
        self.idb_bin = os.environ.get("IDB_BIN") or _default_idb_bin()
        self.companion_path = os.environ.get("IDB_COMPANION_PATH") or _default_companion()

    def observe(self) -> tuple[dict, str]:
        """describe-all + screenshot. Raises IdbError on failure (caller
        retries)."""
        tree = self._describe()
        Path(self.trace_dir).mkdir(parents=True, exist_ok=True)
        screenshot = Path(self.trace_dir) / f"{time.time_ns()}.png"
        self._run("screenshot", str(screenshot))
        return tree, str(screenshot)

    def act(self, step: Step) -> dict:
        """Apply step with bounded retry; poll until the tree settles.
        Returns the settled a11y tree. Raises FlowAborted on persistent
        failure — caller must NOT append a partial step to the trace."""
        last: Exception | None = None
        for i in range(RETRIES):
            try:
                self._apply(step)
                return self._wait_settle()
            except IdbError as e:  # noqa: PERF203 - retry loop
                last = e
                time.sleep(0.4 * (2**i))  # backoff
        raise FlowAborted(f"{step.action} failed after {RETRIES} retries: {last}")

    # --- internals ---------------------------------------------------------

    def _apply(self, step: Step) -> None:
        if step.action == Action.LAUNCH:
            if not self.bundle_id:
                raise IdbError("launch step requires bundle_id or IDB_BUNDLE_ID")
            self._run("launch", self.bundle_id)
            return

        if step.action == Action.TAP:
            if step.target is None:
                raise IdbError("tap step missing target")
            x, y = self.resolve(step.target, self._describe())
            self._run("ui", "tap", _coord(x), _coord(y))
            return

        if step.action == Action.TYPE:
            if step.target is None:
                raise IdbError("type step missing target")
            x, y = self.resolve(step.target, self._describe())
            self._run("ui", "tap", _coord(x), _coord(y))
            self._run("ui", "text", step.value or "")
            return

        if step.action == Action.SWIPE:
            if step.target is None:
                raise IdbError("swipe step missing target")
            x, y = self.resolve(step.target, self._describe())
            direction = step.value or "up"
            end = _swipe_end(x, y, direction)
            self._run("ui", "swipe", _coord(x), _coord(y), _coord(end[0]), _coord(end[1]))
            return

        if step.action == Action.BACK:
            self._run("ui", "key", "HID_KEYBOARD_ESCAPE")
            return

        raise IdbError(f"unsupported action {step.action}")

    def _wait_settle(self) -> dict:
        """Poll describe-all until ui_tree_hash is stable two reads in a row
        or SETTLE_TIMEOUT_S elapses (then raise IdbError)."""
        deadline = time.monotonic() + SETTLE_TIMEOUT_S
        last_hash: str | None = None
        while time.monotonic() < deadline:
            tree = self._describe()
            current = _hash_tree(tree)
            if current == last_hash:
                return tree
            last_hash = current
            time.sleep(0.25)
        raise IdbError("ui tree did not settle")

    def _describe(self) -> dict:
        stdout = self._run("ui", "describe-all", "--json", "--nested")
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as e:
            raise IdbError(f"idb describe-all returned invalid JSON: {e}") from e

    def _run(self, *args: str) -> str:
        cmd = [self.idb_bin]
        if self.companion_path:
            cmd.extend(["--companion-path", self.companion_path])
        cmd.extend(args)
        if self.udid:
            cmd.extend(["--udid", self.udid])
        try:
            result = subprocess.run(cmd, text=True, capture_output=True, check=True)
        except (OSError, subprocess.CalledProcessError) as e:
            stderr = getattr(e, "stderr", "") or str(e)
            raise IdbError(stderr.strip()) from e
        return result.stdout

    @staticmethod
    def resolve(target: Target, tree: dict) -> tuple[float, float]:
        """Selector fallback (locked order): a11y_id -> label -> text ->
        coordinate from the element's describe-all frame. Sets
        target.resolved_by so source_patcher knows which targets are brittle."""
        if target.a11y_id:
            el = _find(tree, "a11y_id", target.a11y_id)
            if el:
                target.resolved_by = "a11y_id"
                return _center(el)
        if target.label:
            el = _find(tree, "label", target.label)
            if el:
                target.resolved_by = "label"
                return _center(el)
        if target.text:
            el = _find(tree, "text", target.text)
            if el:
                target.resolved_by = "text"
                return _center(el)
        if target.coord:
            target.resolved_by = "coord"
            return target.coord
        raise FlowAborted("target not found in accessibility tree")


def _find(tree: dict, kind: str, expected: str) -> dict | None:
    for node in _walk(tree):
        if _matches(node, kind, expected):
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


def _matches(node: dict, kind: str, expected: str) -> bool:
    if kind == "a11y_id":
        values = (
            "identifier",
            "accessibilityIdentifier",
            "AXIdentifier",
            "AXUniqueId",
            "testID",
            "id",
        )
    elif kind == "label":
        values = ("label", "accessibilityLabel", "AXLabel", "name")
    else:
        values = ("text", "title", "value", "AXValue", "label", "AXLabel", "name")
    return any(str(node.get(name, "")) == expected for name in values)


def _center(node: dict) -> tuple[float, float]:
    frame = node.get("frame") or node.get("rect") or node.get("bounds")
    if not isinstance(frame, dict):
        raise FlowAborted("matched element has no frame")

    if "origin" in frame and "size" in frame:
        origin = frame["origin"]
        size = frame["size"]
        x, y = float(origin["x"]), float(origin["y"])
        w, h = float(size["width"]), float(size["height"])
    else:
        x = float(frame.get("x", frame.get("X", 0)))
        y = float(frame.get("y", frame.get("Y", 0)))
        w = float(frame.get("width", frame.get("Width", 0)))
        h = float(frame.get("height", frame.get("Height", 0)))
    return (x + w / 2, y + h / 2)


def _default_idb_bin() -> str:
    venv_idb = Path(sys.executable).with_name("idb")
    if venv_idb.exists():
        return str(venv_idb)
    found = shutil.which("idb")
    if found:
        return found
    return "idb"


def _default_companion() -> str | None:
    for path in ("/opt/homebrew/bin/idb_companion", "/usr/local/bin/idb_companion"):
        if Path(path).exists():
            return path
    return shutil.which("idb_companion")


def _swipe_end(x: float, y: float, direction: str) -> tuple[float, float]:
    delta = 280.0
    if direction == "down":
        return (x, y + delta)
    if direction == "left":
        return (x - delta, y)
    if direction == "right":
        return (x + delta, y)
    return (x, y - delta)


def _coord(value: float) -> str:
    return str(int(round(value)))
