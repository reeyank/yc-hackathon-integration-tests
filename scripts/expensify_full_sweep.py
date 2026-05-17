from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from idb_wrapper import FlowAborted, IdbWrapper
from runner import check
from trace import Action, Assertion, Step, Target


UDID = "C3208EE6-0F0F-4564-82B5-FC13F03C3205"
BUNDLE = "com.expensify.app"
TRACE_DIR = Path("traces/expensify-full-sweep")


def flatten(node):
    out = []
    if isinstance(node, dict):
        out.append(node)
        for key in ("children", "subviews", "elements"):
            for child in node.get(key, []) or []:
                out.extend(flatten(child))
    elif isinstance(node, list):
        for child in node:
            out.extend(flatten(child))
    return out


def label(node: dict) -> str:
    for key in (
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
        "AXValue",
        "value",
    ):
        value = node.get(key)
        if value:
            return str(value)
    return ""


def center(node: dict) -> tuple[float, float]:
    frame = node.get("frame") or node.get("rect") or node.get("bounds") or {}
    return (
        float(frame.get("x", 0)) + float(frame.get("width", 0)) / 2,
        float(frame.get("y", 0)) + float(frame.get("height", 0)) / 2,
    )


class Sweep:
    def __init__(self) -> None:
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        self.idb = IdbWrapper(UDID, str(TRACE_DIR), BUNDLE)
        self.results: list[tuple[str, str, bool, object]] = []
        self.blockers: list[tuple[str, str]] = []

    def observe(self, name: str) -> tuple[dict, list[str], str]:
        tree, shot = self.idb.observe()
        labels = [label(n) for n in flatten(tree) if label(n)]
        (TRACE_DIR / f"{name}.labels.json").write_text(json.dumps(labels, indent=2))
        return tree, labels, shot

    def wait_for_label(self, wanted: tuple[str, ...], name: str, timeout_s: float = 12.0):
        deadline = time.monotonic() + timeout_s
        last = (None, [], "")
        while time.monotonic() < deadline:
            tree, labels, shot = self.observe(name)
            last = (tree, labels, shot)
            if any(any(item == target or target in item for item in labels) for target in wanted):
                return tree, labels, shot
            time.sleep(0.5)
        return last

    def assert_exists(self, tree: dict, selector: str, area: str) -> bool:
        res = check(Assertion("exists", selector), tree)
        self.results.append((area, selector, res.passed, res.actual))
        print(
            "PASS" if res.passed else "FAIL",
            area,
            "exists",
            repr(selector),
            f"actual={res.actual!r}",
        )
        return res.passed

    def act(
        self,
        action: Action,
        target: Target | None = None,
        value: str | None = None,
        name: str = "step",
    ) -> dict:
        tree = self.idb.act(Step(action=action, target=target, value=value))
        _, shot = self.idb.observe()
        print("ACTION", name, action.value, f"screenshot={Path(shot).name}")
        return tree

    def tap_label(self, text: str, name: str | None = None) -> dict:
        return self.act(Action.TAP, Target(label=text, text=text), name=name or f"tap {text}")

    def tap_first_textfield(self, tree: dict, name: str) -> dict:
        nodes = [
            n
            for n in flatten(tree)
            if n.get("role") == "AXTextField"
            or n.get("type") == "TextField"
            or n.get("role_description") == "text field"
        ]
        if not nodes:
            raise FlowAborted("no text field in current accessibility tree")
        x, y = center(nodes[0])
        return self.act(Action.TAP, Target(coord=(x, y)), name=name)

    def run(self) -> None:
        print(
            "SOURCE_EVIDENCE app/auth.tsx AuthScreen/AuthForm drives phone login; "
            "app/index.tsx redirects unauthenticated users to /auth?required=1"
        )
        print(
            "SOURCE_EVIDENCE app/index.tsx main app contains journal, overview, "
            "settings, day details; auth gate must pass before those are reachable"
        )

        self.act(Action.LAUNCH, name="launch Expensify")
        tree, labels, shot = self.wait_for_label(
            ("EXPENSIFY ACCOUNT", "Log expenses", "Welcome", "Account"),
            "01-launch",
        )
        print(f"OBSERVE launch screenshot={Path(shot).name}")
        for selector in (
            "EXPENSIFY ACCOUNT",
            "Account",
            "Continue with phone",
            "Back up your spending history",
            "Restore it on any device",
            "Keep account data private to you",
            "We'll text you a secure code.",
            "Send code",
        ):
            self.assert_exists(tree, selector, "auth_launch")

        try:
            self.tap_label("Send code", "submit empty phone")
            time.sleep(0.8)
            tree, labels, _ = self.observe("02-empty-phone-validation")
            has_validation = any(
                "Check your phone number" in item or "Enter a mobile number" in item
                for item in labels
            )
            self.results.append(
                (
                    "auth_validation",
                    "Check your phone number alert",
                    has_validation,
                    "exists" if has_validation else "missing",
                )
            )
            print(
                "PASS" if has_validation else "FAIL",
                "auth_validation",
                repr("Check your phone number alert"),
                f"actual={'exists' if has_validation else 'missing'!r}",
            )
            if any(item == "OK" for item in labels):
                self.tap_label("OK", "dismiss validation alert")
        except Exception as exc:
            self.blockers.append(("auth_validation", str(exc)))
            print("BLOCK auth_validation", exc)

        try:
            tree, _, _ = self.observe("03-before-phone-entry")
            self.tap_first_textfield(tree, "focus phone field")
            self.act(
                Action.TYPE,
                Target(coord=(201, 575)),
                value="5551234567",
                name="type phone number",
            )
            self.tap_label("Send code", "request SMS code")
            time.sleep(4.0)
            tree, labels, _ = self.observe("04-after-send-code")
            reached_code = any(
                "Verification code" in item
                or "Verify and continue" in item
                or "Code sent to" in item
                for item in labels
            )
            auth_failed = any(
                "Auth failed" in item
                or "Could not send code" in item
                or "failed" in item.lower()
                for item in labels
            )
            actual = "exists" if reached_code else ("auth_failed" if auth_failed else "missing")
            self.results.append(("auth_send_code", "code entry screen", reached_code, actual))
            print(
                "PASS" if reached_code else "FAIL",
                "auth_send_code",
                repr("code entry screen"),
                f"actual={actual!r}",
            )

            if reached_code:
                self.tap_first_textfield(tree, "focus verification code")
                self.act(
                    Action.TYPE,
                    Target(coord=(201, 575)),
                    value="000000",
                    name="type verification code",
                )
                self.tap_label("Verify and continue", "submit verification code")
                time.sleep(5.0)
                tree, labels, _ = self.observe("05-after-verify-code")
                main_reached = any(
                    item in labels for item in ("Log expenses", "Settings", "Today")
                ) or any("Log expenses" in item or "Write your first expense" in item for item in labels)
                self.results.append(
                    (
                        "auth_verify",
                        "main app reachable",
                        main_reached,
                        "exists" if main_reached else "missing",
                    )
                )
                print(
                    "PASS" if main_reached else "FAIL",
                    "auth_verify",
                    repr("main app reachable"),
                    f"actual={'exists' if main_reached else 'missing'!r}",
                )
                if main_reached:
                    for selector in ("Log expenses", "Settings"):
                        self.assert_exists(tree, selector, "main_app")
            else:
                self.blockers.append(
                    (
                        "main_app",
                        "Blocked before main app: phone-code screen was not reached; "
                        "live labels saved in 04-after-send-code.labels.json",
                    )
                )
        except Exception as exc:
            self.blockers.append(("auth_send_code", str(exc)))
            print("BLOCK auth_send_code", exc)

        failed = sum(1 for _, _, passed, _ in self.results if not passed)
        print(
            "SUMMARY",
            f"assertions={len(self.results)}",
            f"failed={failed}",
            f"blockers={len(self.blockers)}",
        )
        for area, reason in self.blockers:
            print("BLOCKER", area, reason)


if __name__ == "__main__":
    Sweep().run()
