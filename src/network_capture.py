"""Proxy/network event ingestion for agent runs.

The agent can consume HAR files or JSONL produced by proxy tooling. Keeping this
as a neutral event format lets the TUI and OpenAI planner reason over backend
behavior without coupling the core tester to a specific proxy implementation.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass
class NetworkEvent:
    method: str
    url: str
    status: int | None = None
    request_bytes: int | None = None
    response_bytes: int | None = None
    error: str | None = None

    def compact(self) -> dict[str, object]:
        parsed = urlparse(self.url)
        return {
            "method": self.method,
            "status": self.status,
            "host": parsed.netloc,
            "path": parsed.path or "/",
            "error": self.error,
        }


def load_network_events(path: str | None) -> list[NetworkEvent]:
    if not path:
        return []
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"proxy log not found: {source}")
    if source.suffix.lower() == ".har":
        return _load_har(source)
    return _load_jsonl(source)


def summarize(events: list[NetworkEvent]) -> dict[str, object]:
    failures = [event for event in events if event.error or (event.status and event.status >= 400)]
    hosts = sorted({urlparse(event.url).netloc for event in events if event.url})
    return {
        "count": len(events),
        "failures": len(failures),
        "hosts": hosts[:12],
        "recent": [event.compact() for event in events[-12:]],
        "failed": [event.compact() for event in failures[-12:]],
    }


def write_jsonl(events: list[NetworkEvent], path: str) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(asdict(event), sort_keys=True) + "\n")


def _load_jsonl(path: Path) -> list[NetworkEvent]:
    events: list[NetworkEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(
            NetworkEvent(
                method=str(raw.get("method", "GET")),
                url=str(raw["url"]),
                status=_int_or_none(raw.get("status")),
                request_bytes=_int_or_none(raw.get("request_bytes")),
                response_bytes=_int_or_none(raw.get("response_bytes")),
                error=raw.get("error"),
            )
        )
    return events


def _load_har(path: Path) -> list[NetworkEvent]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = raw.get("log", {}).get("entries", [])
    events: list[NetworkEvent] = []
    for entry in entries:
        request = entry.get("request", {})
        response = entry.get("response", {})
        events.append(
            NetworkEvent(
                method=str(request.get("method", "GET")),
                url=str(request.get("url", "")),
                status=_int_or_none(response.get("status")),
                request_bytes=_int_or_none(request.get("bodySize")),
                response_bytes=_int_or_none(response.get("bodySize")),
                error=entry.get("_error"),
            )
        )
    return events


def _int_or_none(value: object) -> int | None:
    if value in (None, "", -1):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
