"""testID auto-patch with reviewable diff (amendment).

Locked: the ONLY place this tool writes to the user's codebase. When a tested
element lacks a stable selector (resolved_by != "a11y_id"), gbrain code-def
locates the component, inject a deterministic testID into the .tsx, and
present the change as a git diff the user accepts/rejects. NEVER silent.

Hackathon scope: common RN patterns only — TouchableOpacity, Pressable,
Button, TextInput. Exotic/custom-wrapped components fall back to a fix-prompt
(emit the suggested edit as text), NOT auto-patch.
"""

from __future__ import annotations

import difflib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from trace import Target


@dataclass
class PatchProposal:
    file: str
    line: int
    component: str
    test_id: str
    diff: str  # unified git diff, shown to the user verbatim
    auto_patchable: bool  # False -> emit as fix-prompt instead


def propose(target: Target, app_path: str) -> PatchProposal | None:
    """For a brittle (coord/text-resolved) target, use gbrain code-def to
    find the component, decide if it's an auto-patchable RN pattern, and
    build a unified diff. Returns None if the target is already stable."""
    if target.is_stable():
        return None

    selector = target.label or target.text
    if not selector:
        return PatchProposal(
            file="",
            line=0,
            component="unknown",
            test_id="",
            diff="",
            auto_patchable=False,
        )

    root = Path(app_path)
    test_id = _test_id(selector)
    for path in sorted(root.rglob("*")):
        if path.suffix not in {".tsx", ".jsx"} or "node_modules" in path.parts:
            continue
        proposal = _proposal_for_file(root, path, selector, test_id)
        if proposal:
            return proposal

    return PatchProposal(
        file="",
        line=0,
        component="unknown",
        test_id=test_id,
        diff="",
        auto_patchable=False,
    )


def apply(proposal: PatchProposal) -> None:
    """Apply the patch ONLY after explicit user approval of the diff.
    Never call this without surfacing proposal.diff to the user first."""
    if not proposal.auto_patchable or not proposal.diff:
        raise ValueError("proposal is not auto-patchable")
    subprocess.run(["git", "apply"], input=proposal.diff, text=True, check=True)


def as_fix_prompt(proposal: PatchProposal) -> str:
    """Render a non-auto-patchable proposal as a paste-ready fix prompt
    (the 'blocked flow' findings-report path)."""
    location = f"{proposal.file}:{proposal.line}" if proposal.file else "the RN source"
    return (
        f"Add a stable React Native testID for `{proposal.component}` at {location}. "
        f"Use testID=\"{proposal.test_id}\" on the interactive element, keep the "
        "existing accessibilityLabel, and rerun ios-test."
    )


def _proposal_for_file(
    root: Path, path: Path, selector: str, test_id: str
) -> PatchProposal | None:
    original = path.read_text(encoding="utf-8").splitlines(keepends=True)
    for index, line in enumerate(original):
        if f'accessibilityLabel="{selector}"' not in line:
            continue
        start = _opening_tag_start(original, index)
        if start is None or "testID=" in "".join(original[start : index + 1]):
            return None
        component = _component_name(original[start])
        if component not in {"Pressable", "TouchableOpacity", "Button", "TextInput"}:
            return PatchProposal(
                file=str(path.relative_to(root)),
                line=index + 1,
                component=component,
                test_id=test_id,
                diff="",
                auto_patchable=False,
            )
        changed = original[:]
        indent = re.match(r"(\s*)", original[index]).group(1)
        changed.insert(index, f'{indent}testID="{test_id}"\n')
        diff = "".join(
            difflib.unified_diff(
                original,
                changed,
                fromfile=str(path),
                tofile=str(path),
            )
        )
        return PatchProposal(
            file=str(path.relative_to(root)),
            line=index + 1,
            component=component,
            test_id=test_id,
            diff=diff,
            auto_patchable=True,
        )
    return None


def _opening_tag_start(lines: list[str], index: int) -> int | None:
    for cursor in range(index, max(index - 8, -1), -1):
        if re.search(r"<(Pressable|TouchableOpacity|Button|TextInput)\b", lines[cursor]):
            return cursor
    return None


def _component_name(line: str) -> str:
    match = re.search(r"<([A-Z]\w*)\b", line)
    return match.group(1) if match else "unknown"


def _test_id(selector: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", selector.lower()).strip("-")
    return f"gbrain-{slug or 'target'}"
