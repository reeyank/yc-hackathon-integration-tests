"""Trace -> semantic coverage data for the T8 web view.

The HTML is intentionally static. This module produces the small JSON payload
it needs from the same Trace consumed by the replay runner and Detox codegen.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trace import Trace


def build(trace: Trace) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    events: list[dict[str, str]] = []
    seen_nodes: set[str] = set()
    seen_edges: set[tuple[str, str]] = set()
    dark_symbols: set[str] = set()
    exercised_symbols: set[str] = set()

    for flow in trace.flows:
        symbols = flow.gbrain_symbols or [flow.name]
        passed = flow.status == "passed"
        for symbol in symbols:
            if symbol not in seen_nodes:
                nodes.append({"id": symbol, "flow": flow.name})
                seen_nodes.add(symbol)
            if passed:
                exercised_symbols.add(symbol)
            else:
                dark_symbols.add(symbol)

        if len(symbols) == 1:
            events.append({"flow": flow.name, "to": symbols[0]})
            continue

        for source, target in zip(symbols, symbols[1:]):
            edge = (source, target)
            if edge not in seen_edges:
                edges.append({"source": source, "target": target})
                seen_edges.add(edge)
            events.append({"flow": flow.name, "from": source, "to": target})

    dark_symbols -= exercised_symbols
    return {
        "schema_version": 1,
        "app_path": trace.app_path,
        "summary": {
            "flows_total": len(trace.flows),
            "flows_passed": sum(1 for flow in trace.flows if flow.status == "passed"),
            "symbols_total": len(nodes),
            "symbols_dark": len(dark_symbols),
        },
        "nodes": nodes,
        "edges": edges,
        "events": events,
        "dark_symbols": sorted(dark_symbols),
        "flows": [
            {
                "name": flow.name,
                "status": flow.status,
                "symbols": flow.gbrain_symbols,
                "failure": flow.failure,
            }
            for flow in trace.flows
        ],
    }


def write(trace: Trace, path: str | Path) -> None:
    Path(path).write_text(json.dumps(build(trace), indent=2), encoding="utf-8")
