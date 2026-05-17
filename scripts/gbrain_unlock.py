#!/usr/bin/env python3
"""Safely clear a stale project-local gbrain PGLite lock.

Only removes `.gbrain-lock` when no gbrain process is alive. This is a recovery
tool for interrupted queries, not a way to disable PGLite locking.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    gbrain_home = Path(os.environ.get("GBRAIN_HOME", project / ".gbrain-runtime"))
    lock_dir = gbrain_home / ".gbrain" / "brain.pglite" / ".gbrain-lock"

    processes = _gbrain_processes()
    if processes:
        print("Refusing to remove lock while gbrain is running:", file=sys.stderr)
        for line in processes:
            print(line, file=sys.stderr)
        return 2

    if not lock_dir.exists():
        print(f"No lock present at {lock_dir}")
        return 0

    shutil.rmtree(lock_dir)
    print(f"Removed stale lock: {lock_dir}")
    return 0


def _gbrain_processes() -> list[str]:
    parent = str(os.getppid())
    result = subprocess.run(
        ["ps", "-axo", "pid,ppid,command"],
        text=True,
        capture_output=True,
        check=False,
    )
    current = str(os.getpid())
    rows: list[str] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        pid, ppid, command = parts
        if pid == current or pid == parent:
            continue
        if "gbrain" not in command:
            continue
        if "gbrain_unlock.py" in command or "scripts/gbrain-project unlock" in command:
            continue
        rows.append(line.strip())
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
