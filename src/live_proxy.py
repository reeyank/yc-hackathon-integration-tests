"""Optional live HTTP(S) capture backend for agent runs.

The tester keeps network data in the neutral JSONL format from
network_capture.py. This module starts mitmdump when available and streams
requests/responses into that file while the agent is driving the simulator.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from network_capture import NetworkEvent, load_network_events


class LiveProxyUnavailable(RuntimeError):
    """The live proxy backend cannot be started on this machine."""


class LiveProxyCapture:
    def __init__(
        self,
        out: str,
        port: int = 9090,
        host: str = "127.0.0.1",
        binary: str | None = None,
    ) -> None:
        self.out = Path(out)
        self.port = port
        self.host = host
        self.binary = binary or os.environ.get("IOS_TEST_MITMDUMP_BIN") or "mitmdump"
        self.process: subprocess.Popen[str] | None = None
        self.addon_path: Path | None = None

    @property
    def proxy_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        binary = shutil.which(self.binary)
        if not binary:
            raise LiveProxyUnavailable(
                "mitmdump is required for --live-proxy. Install mitmproxy, then "
                "point the simulator/app at the printed proxy URL. HTTPS capture "
                "also requires trusting mitmproxy's certificate in the simulator."
            )

        self.out.parent.mkdir(parents=True, exist_ok=True)
        self.out.write_text("", encoding="utf-8")
        self.addon_path = Path(_write_addon(self.out))
        self.process = subprocess.Popen(
            [
                binary,
                "-q",
                "--listen-host",
                self.host,
                "--listen-port",
                str(self.port),
                "-s",
                str(self.addon_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            self.process.wait(timeout=0.7)
        except subprocess.TimeoutExpired:
            return
        stderr = self.process.stderr.read() if self.process.stderr else ""
        raise LiveProxyUnavailable(stderr.strip() or "mitmdump exited before capture started")

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.process = None
        if self.addon_path:
            try:
                self.addon_path.unlink()
            except OSError:
                pass
            self.addon_path = None

    def events(self) -> list[NetworkEvent]:
        return load_network_events(str(self.out))

    def __enter__(self) -> "LiveProxyCapture":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()


def _write_addon(out: Path) -> str:
    script = f"""
import json
from pathlib import Path

OUT = Path({str(out)!r})


def _write(row):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\\n")


def response(flow):
    request = flow.request
    response = flow.response
    _write({{
        "method": request.method,
        "url": request.pretty_url,
        "status": response.status_code if response else None,
        "request_bytes": len(request.raw_content or b""),
        "response_bytes": len(response.raw_content or b"") if response else None,
        "error": None,
    }})


def error(flow):
    request = flow.request
    _write({{
        "method": request.method,
        "url": request.pretty_url,
        "status": None,
        "request_bytes": len(request.raw_content or b""),
        "response_bytes": None,
        "error": str(flow.error) if flow.error else "proxy error",
    }})
"""
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".py",
        prefix="ios-test-mitm-",
        delete=False,
    )
    with handle:
        handle.write(script)
    return handle.name
