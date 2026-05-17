"""Per-app gbrain source preparation.

The tester should behave like it has never seen the target app before unless
the caller explicitly points at an existing source. Each app path gets a stable
source id and all gbrain lookups for that run are scoped to that id.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path


class GBrainSourceError(RuntimeError):
    """The target app could not be registered or synced in gbrain."""


def source_id_for_path(app_path: str | Path) -> str:
    root = Path(app_path).resolve()
    base = re.sub(r"[^a-z0-9]+", "-", root.name.lower()).strip("-") or "app"
    digest = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:8]
    return f"app-{base}-{digest}-scoped"


def prepare_app_source(
    app_path: str | Path,
    source_id: str | None = None,
    *,
    fresh: bool = False,
    sync: bool = True,
) -> str:
    root = Path(app_path).resolve()
    if not root.exists():
        raise GBrainSourceError(f"app path does not exist: {root}")
    source = source_id or source_id_for_path(root)
    sync_path = _build_scoped_source(root, source)
    if fresh:
        _run_gbrain("sources", "remove", source, "--confirm-destructive", check=False)
    added = _run_gbrain("sources", "add", source, "--path", str(sync_path), check=False)
    if added.returncode != 0 and "already" not in (added.stderr + added.stdout).lower():
        raise GBrainSourceError((added.stderr or added.stdout).strip())
    if sync:
        synced = _run_gbrain("sync", "--source", source, "--strategy", "code", check=False)
        if synced.returncode != 0:
            raise GBrainSourceError((synced.stderr or synced.stdout).strip())
    os.environ["GBRAIN_SOURCE"] = source
    return source


def _run_gbrain(*args: str, check: bool) -> subprocess.CompletedProcess[str]:
    binary = os.environ.get("GBRAIN_BIN", "gbrain")
    timeout = float(os.environ.get("GBRAIN_SYNC_TIMEOUT_S", "900"))
    try:
        return subprocess.run(
            [binary, *args],
            capture_output=True,
            text=True,
            check=check,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise GBrainSourceError(
            f"gbrain {' '.join(args)} timed out after {e.timeout}s; "
            "increase GBRAIN_SYNC_TIMEOUT_S for very large apps"
        ) from e


def _build_scoped_source(root: Path, source_id: str) -> Path:
    out_root = Path(os.environ.get("GBRAIN_SCOPED_SOURCE_ROOT", ".gbrain-target-sources"))
    out = (out_root / source_id).resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    copied = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or _is_ignored(path, root):
            continue
        rel = path.relative_to(root)
        if not _is_syncable_app_file(rel):
            continue
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1

    if copied == 0:
        raise GBrainSourceError(f"no syncable app source files found under {root}")
    (out / "IOS_TEST_SOURCE_ROOT.txt").write_text(str(root) + "\n", encoding="utf-8")
    _init_scoped_git(out)
    return out


def _init_scoped_git(path: Path) -> None:
    commands = [
        ["git", "init", "-q"],
        ["git", "config", "user.email", "ios-test@example.local"],
        ["git", "config", "user.name", "ios-test"],
        ["git", "config", "commit.gpgsign", "false"],
        ["git", "add", "."],
        ["git", "commit", "-qm", "ios-test scoped source snapshot"],
    ]
    for command in commands:
        result = subprocess.run(command, cwd=path, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise GBrainSourceError(
                f"failed to prepare scoped git source at {path}: "
                f"{' '.join(command)}: {(result.stderr or result.stdout).strip()}"
            )


def _is_ignored(path: Path, root: Path) -> bool:
    rel_parts = path.relative_to(root).parts
    ignored = {
        ".git",
        ".expo",
        ".next",
        ".turbo",
        "node_modules",
        "Pods",
        "build",
        "dist",
        "coverage",
        "DerivedData",
        ".gradle",
        "android",
    }
    if any(part in ignored for part in rel_parts):
        return True
    if len(rel_parts) >= 2 and rel_parts[0] == "ios" and rel_parts[1] in {"Pods", "build"}:
        return True
    return False


def _is_syncable_app_file(rel: Path) -> bool:
    if rel.suffix not in {".ts", ".tsx", ".js", ".jsx", ".json"}:
        return rel.name in {"README.md"}
    top = rel.parts[0] if rel.parts else ""
    app_dirs = {
        "app",
        "src",
        "components",
        "context",
        "hooks",
        "lib",
        "utils",
        "config",
        "constants",
        "stores",
        "services",
        "screens",
        "navigation",
    }
    root_files = {
        "package.json",
        "app.json",
        "app.config.js",
        "app.config.ts",
        "expo-env.d.ts",
        "tsconfig.json",
        "babel.config.js",
        "metro.config.js",
        "index.js",
        "index.ts",
        "App.tsx",
        "App.jsx",
        "App.js",
    }
    return top in app_dirs or str(rel) in root_files
