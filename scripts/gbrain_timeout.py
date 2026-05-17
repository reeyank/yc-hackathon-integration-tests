#!/usr/bin/env python3
"""Run gbrain query/ask with a hard timeout while streaming output.

PGLite allows one active connection. In this project, `gbrain query` can print
useful ranked retrieval hits and then keep the process alive. This wrapper
prevents that from leaving the local brain locked.
"""

from __future__ import annotations

import os
import select
import signal
import subprocess
import sys
import time


def main() -> int:
    timeout_s = float(os.environ.get("GBRAIN_PROJECT_QUERY_TIMEOUT_S", "20"))
    cmd = ["gbrain", *sys.argv[1:]]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    start = time.monotonic()
    assert proc.stdout is not None
    try:
        while True:
            ready, _, _ = select.select([proc.stdout], [], [], 0.1)
            if ready:
                chunk = proc.stdout.readline()
                if chunk:
                    print(chunk, end="", flush=True)
            if proc.poll() is not None:
                remainder = proc.stdout.read()
                if remainder:
                    print(remainder, end="", flush=True)
                return int(proc.returncode or 0)
            if time.monotonic() - start > timeout_s:
                _terminate_group(proc)
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    _kill_group(proc)
                    proc.wait(timeout=2)
                remainder = proc.stdout.read()
                if remainder:
                    print(remainder, end="", flush=True)
                print(
                    f"[gbrain-project] stopped gbrain after {timeout_s:g}s to release the PGLite lock",
                    file=sys.stderr,
                    flush=True,
                )
                return 0
            time.sleep(0.05)
    except KeyboardInterrupt:
        _terminate_group(proc)
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
        raise


def _terminate_group(proc: subprocess.Popen[str]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def _kill_group(proc: subprocess.Popen[str]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
