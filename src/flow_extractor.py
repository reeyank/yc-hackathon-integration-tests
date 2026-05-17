"""gbrain flow extractor (T4).

RN pivot (amendment): source is JS/TS/TSX, not Swift. gbrain indexes JS/TS
well even on 0.18.2, so this is the low-risk path. Runs gbrain over the RN
source to produce a flow list the explorer can pursue.

Output is the `gbrain_symbols` + `hints` that seed each Flow:

    {"flow": "create_item",
     "gbrain_symbols": ["CreateItemScreen", "itemStore.add"],
     "hints": ["Add", "Title", "Save"]}

gbrain calls (subprocess; language-agnostic CLI):
    gbrain code-def <ScreenComponent>
    gbrain code-refs <store/action>
    gbrain search "navigation between screens"
"""

from __future__ import annotations

import os
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FlowSpec:
    flow: str
    gbrain_symbols: list[str]
    hints: list[str]  # text/labels the explorer should look for to navigate
    gbrain_evidence: list[str] = field(default_factory=list)
    route: str | None = None
    source_file: str | None = None
    priority: int = 50
    kind: str = "flow"


class GBrainUnavailable(RuntimeError):
    """gbrain is required for normal flow extraction and could not answer."""


def _gbrain(*args: str) -> str:
    """Run a gbrain CLI command; return stdout.

    The CLI prepares GBRAIN_SOURCE per app before calling this module, so
    lookups are scoped to the current target repo instead of a global default.
    """
    binary = os.environ.get("GBRAIN_BIN", "gbrain")
    timeout = float(os.environ.get("GBRAIN_TIMEOUT_S", "35"))
    return subprocess.run(
        [binary, *args], capture_output=True, text=True, check=True, timeout=timeout
    ).stdout


def _gbrain_input(args: list[str], content: str) -> str:
    binary = os.environ.get("GBRAIN_BIN", "gbrain")
    return subprocess.run(
        [binary, *args],
        input=content,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _try_gbrain(*args: str) -> tuple[str, str | None]:
    try:
        return _gbrain(*args), None
    except FileNotFoundError as e:
        return "", str(e)
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        stdout = (e.stdout or "").strip()
        detail = stderr or stdout or str(e)
        return "", detail
    except subprocess.TimeoutExpired as e:
        stdout = _timeout_text(e.stdout)
        stderr = _timeout_text(e.stderr)
        if _usable_output(stdout):
            return stdout, f"timed out after {e.timeout}s after partial output"
        return "", stderr or f"timed out after {e.timeout}s"


def _timeout_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def extract_flows(app_path: str, allow_local_fallback: bool = False) -> list[FlowSpec]:
    """Derive candidate flows from the RN source via gbrain.

    Hour-one spike (do this BEFORE building the explorer):
        gbrain code-def <YourScreen>
        gbrain search "navigation between screens"
    Confirm usable symbols come back. If gbrain returns junk on .tsx, fix the
    query strategy here NOW — everything downstream assumes this works.
    """
    root = Path(app_path)
    source = _read_source(root)
    evidence, errors = _collect_gbrain_evidence(source)
    if not _has_symbol_evidence(evidence):
        if allow_local_fallback or os.environ.get("IOS_TEST_ALLOW_LOCAL_FALLBACK") == "1":
            flows = _flows_from_source(source)
            for flow in flows:
                flow.gbrain_evidence.append(
                    "LOCAL_FALLBACK: gbrain unavailable; flow shape parsed from RN source"
                )
            return flows
        detail = "; ".join(errors) if errors else "no gbrain search/code-def hits"
        raise GBrainUnavailable(
            "gbrain did not return usable flow evidence. "
            "Run `ios-test gbrain-plan <app>` after fixing gbrain indexing, or pass "
            "`--allow-local-fallback` only for an environment smoke test. "
            f"Details: {detail}"
        )

    flows = _flows_from_source(source)
    _attach_gbrain_evidence(flows, evidence)
    return flows


def _collect_gbrain_evidence(source: str) -> tuple[dict[str, list[str]], list[str]]:
    evidence: dict[str, list[str]] = {}
    errors: list[str] = []

    for symbol in sorted(_screen_symbols(source)):
        output, error = _try_gbrain("code-def", symbol)
        if _usable_output(output):
            evidence.setdefault(symbol, []).append(_summarize(f"code-def {symbol}", output))
        elif error and "Unknown command: code-def" in error:
            output, search_error = _try_gbrain("search", symbol)
            if _usable_output(output):
                evidence.setdefault(symbol, []).append(
                    _summarize(f"legacy-search {symbol}", output)
                )
            elif search_error:
                errors.append(f"gbrain search {symbol!r}: {search_error}")
        elif error:
            errors.append(f"gbrain code-def {symbol!r}: {error}")

    for symbol in ("finishOnboarding", "createItem", "createItemStore"):
        output, error = _try_gbrain("code-refs", symbol)
        if _usable_output(output):
            evidence.setdefault(symbol, []).append(_summarize(f"code-refs {symbol}", output))
        elif error and "Unknown command: code-refs" in error:
            output, search_error = _try_gbrain("search", symbol)
            if _usable_output(output):
                evidence.setdefault(symbol, []).append(
                    _summarize(f"legacy-search {symbol}", output)
                )
            elif search_error:
                errors.append(f"gbrain search {symbol!r}: {search_error}")
        elif error:
            errors.append(f"gbrain code-refs {symbol!r}: {error}")

    return evidence, errors


def _has_symbol_evidence(evidence: dict[str, list[str]]) -> bool:
    return any(key != "__search__" and hits for key, hits in evidence.items())


def _usable_output(output: str) -> bool:
    stripped = "\n".join(_content_lines(output)).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict) and "count" in parsed:
        return int(parsed.get("count") or 0) > 0
    return bool(stripped) and stripped.lower() != "no results."


def _attach_gbrain_evidence(flows: list[FlowSpec], evidence: dict[str, list[str]]) -> None:
    search_hits = evidence.get("__search__", [])
    for flow in flows:
        hits = list(search_hits)
        for symbol in flow.gbrain_symbols:
            hits.extend(evidence.get(symbol, []))
        flow.gbrain_evidence = hits


def _summarize(label: str, output: str) -> str:
    content = "\n".join(_content_lines(output)).strip()
    parsed: object | None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict) and isinstance(parsed.get("results"), list):
        result = parsed["results"][0] if parsed["results"] else {}
        if isinstance(result, dict):
            file = result.get("file") or result.get("slug") or "unknown"
            start = result.get("start_line")
            symbol_type = result.get("symbol_type")
            first = f"{file}:{start} {symbol_type or ''}".strip()
        else:
            first = content.splitlines()[0] if content else ""
    else:
        first = next((line for line in _content_lines(output) if line), "")
    if len(first) > 220:
        first = first[:217] + "..."
    return f"{label}: {first}"


def _content_lines(output: str) -> list[str]:
    lines: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("[ai.gateway]") or stripped.startswith("[gbrain]"):
            continue
        lines.append(stripped)
    return lines


def index_source(app_path: str) -> list[str]:
    """Compatibility indexer for older/non-code-sync setups.

    Stores the RN source as gbrain pages so keyword search can still provide
    gbrain evidence. Newer gbrain installs should prefer `gbrain sync
    --strategy code`, which powers code-def/code-refs.
    """
    root = Path(app_path)
    indexed: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
            continue
        if {"node_modules", "Pods", "build", "build-release"} & set(path.parts):
            continue
        rel = path.relative_to(root)
        slug = "ios-test-code-" + re.sub(r"[^a-z0-9]+", "-", f"{root.name}-{rel}".lower()).strip("-")
        _gbrain_input(["put", slug], _code_page(root.name, rel, path.read_text(encoding="utf-8")))
        indexed.append(slug)
    if not indexed:
        raise FileNotFoundError(f"no RN source files found under {root}")
    return indexed


def _code_page(app_name: str, rel: Path, source: str) -> str:
    symbols = sorted(_screen_symbols(source) | set(_action_symbols(source)))
    lang = rel.suffix.lstrip(".") or "tsx"
    return (
        f"# Code: {app_name}/{rel}\n\n"
        f"Symbols: {', '.join(symbols)}\n\n"
        f"```{lang}\n{source}\n```\n"
    )


def _read_source(root: Path) -> str:
    chunks: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
            continue
        if "node_modules" in path.parts:
            continue
        chunks.append(f"\n// FILE: {path.relative_to(root)}\n")
        chunks.append(path.read_text(encoding="utf-8"))
    if not chunks:
        raise FileNotFoundError(f"no RN source files found under {root}")
    return "\n".join(chunks)


def _flows_from_source(source: str) -> list[FlowSpec]:
    screens = _screen_symbols(source)
    flows: list[FlowSpec] = _route_flows(source)

    if "OnboardingScreen" in screens:
        flows.append(
            FlowSpec(
                flow="onboarding",
                gbrain_symbols=["OnboardingScreen", "finishOnboarding", "ItemListScreen"],
                hints=["Continue"],
                route="/onboarding",
                source_file="app/onboarding.tsx",
                priority=1,
            )
        )

    if "ItemListScreen" in screens:
        flows.append(
            FlowSpec(
                flow="browse_items",
                gbrain_symbols=["ItemListScreen", "itemStore.fetch", "DetailScreen"],
                hints=["Items", "Open", "Back to list"],
                route="/",
                source_file="app/index.tsx",
                priority=20,
            )
        )

    if "CreateItemScreen" in screens:
        flows.append(
            FlowSpec(
                flow="create_item",
                gbrain_symbols=["CreateItemScreen", "createItem", "itemStore.add"],
                hints=["Add item", "Title", "Save", "Saved"],
                route="/",
                source_file="app/index.tsx",
                priority=10,
            )
        )

    if "SettingsScreen" in screens:
        flows.append(
            FlowSpec(
                flow="settings",
                gbrain_symbols=["SettingsScreen"],
                hints=["Settings", "Back to list"],
                route="/settings",
                source_file="app/settings.tsx",
                priority=30,
            )
        )

    if flows:
        return _dedupe_flows(flows)

    labels = re.findall(r'accessibilityLabel="([^"]+)"', source)
    test_ids = re.findall(r'testID="([^"]+)"', source)
    return [
        FlowSpec(
            flow="discovered_interactions",
            gbrain_symbols=sorted(screens),
            hints=labels or test_ids,
            priority=99,
        )
    ]


def _route_flows(source: str) -> list[FlowSpec]:
    flows: list[FlowSpec] = []
    for rel, body in _source_files(source).items():
        if not rel.startswith("app/") or rel.endswith("/_layout.tsx"):
            continue
        if not rel.endswith((".tsx", ".ts", ".jsx", ".js")):
            continue
        route = _route_from_file(rel)
        name = _flow_name_from_route(route)
        symbols = _file_symbols(body, rel)
        hints = _hints_from_file(body, route)
        flows.append(
            FlowSpec(
                flow=name,
                gbrain_symbols=symbols,
                hints=hints,
                route=route,
                source_file=rel,
                priority=_route_priority(route),
                kind="route",
            )
        )
        for feature in _feature_flows(rel, body, route, symbols):
            flows.append(feature)
    return _dedupe_flows(flows)


def _source_files(source: str) -> dict[str, str]:
    files: dict[str, list[str]] = {}
    current: str | None = None
    for line in source.splitlines():
        match = re.match(r"// FILE: (.+)", line)
        if match:
            current = match.group(1).strip()
            files[current] = []
            continue
        if current:
            files[current].append(line)
    return {path: "\n".join(lines) for path, lines in files.items()}


def _route_from_file(rel: str) -> str:
    route = rel.removeprefix("app/")
    route = re.sub(r"\.(tsx|ts|jsx|js)$", "", route)
    if route == "index":
        return "/"
    return "/" + route


def _flow_name_from_route(route: str) -> str:
    if route == "/":
        return "home_dashboard"
    return route.strip("/").replace("/", "_").replace("-", "_")


def _route_priority(route: str) -> int:
    order = {
        "/onboarding": 1,
        "/auth": 5,
        "/": 10,
        "/day-details": 20,
        "/settings": 30,
    }
    return order.get(route, 60)


def _file_symbols(body: str, rel: str) -> list[str]:
    symbols = re.findall(r"export\s+default\s+function\s+([A-Z]\w*)", body)
    symbols.extend(re.findall(r"function\s+([A-Z]\w*)\b", body))
    if not symbols:
        symbols.append(_flow_name_from_route(_route_from_file(rel)))
    return sorted(dict.fromkeys(symbols))


def _hints_from_file(body: str, route: str) -> list[str]:
    labels = re.findall(r'accessibilityLabel="([^"]+)"', body)
    test_ids = re.findall(r'testID="([^"]+)"', body)
    texts = re.findall(r"<Text[^>]*>\s*([^<{]{2,60}?)\s*</Text>", body)
    string_literals = re.findall(r'"([A-Z][^"]{2,50})"', body)
    candidates = labels + test_ids + texts + string_literals
    hints: list[str] = []
    for value in candidates:
        cleaned = re.sub(r"\s+", " ", value).strip()
        if not cleaned or cleaned.startswith((".", "/", "{")):
            continue
        if cleaned not in hints:
            hints.append(cleaned)
    defaults = {
        "/onboarding": ["Get Started", "Continue", "Skip for now", "Start tracking"],
        "/auth": ["Phone number", "Continue", "Verification code", "Verify"],
        "/": ["Today", "Settings", "Write a note", "Add", "Save"],
        "/settings": ["Settings", "Sign in and sync", "Currency", "Export", "Clear All Data"],
        "/day-details": ["Back", "Category", "Restore", "Exclude"],
    }
    return (defaults.get(route, []) + [hint for hint in hints if hint not in defaults.get(route, [])])[:12]


def _feature_flows(rel: str, body: str, route: str, symbols: list[str]) -> list[FlowSpec]:
    flows: list[FlowSpec] = []
    features = [
        ("auth_phone_otp", ("Phone number", "Verification code", "authClient", "signIn")),
        ("create_expense", ("Write a note", "parseEntryWithAI", "Save", "spent")),
        ("fixed_expense", ("fixed", "parseFixedExpenseWithAI", "Recurring")),
        ("settings_export", ("Export", "shareAsync", "expenses.csv")),
        ("settings_currency", ("Currency", "CURRENCIES", "updateSettings")),
        ("clear_data", ("Clear All Data", "clearAllData")),
        ("day_detail_category", ("showCatPicker", "updateExpenseCategory", "Category")),
        ("backend_parse", ("parseExpenseOnBackend", "parseFixedExpenseOnBackend")),
        ("dev_panel", ("DevPanel", "Request Log", "versionTaps")),
    ]
    for name, needles in features:
        matched = [needle for needle in needles if needle in body]
        if not matched:
            continue
        flows.append(
            FlowSpec(
                flow=name,
                gbrain_symbols=symbols + matched[:2],
                hints=list(matched)[:8],
                route=route,
                source_file=rel,
                priority=_route_priority(route) + 1,
                kind="feature",
            )
        )
    return flows


def _dedupe_flows(flows: list[FlowSpec]) -> list[FlowSpec]:
    seen: set[str] = set()
    unique: list[FlowSpec] = []
    for flow in sorted(flows, key=lambda f: (f.priority, f.flow)):
        if flow.flow in seen:
            continue
        seen.add(flow.flow)
        unique.append(flow)
    return unique


def _screen_symbols(source: str) -> set[str]:
    return set(re.findall(r"function\s+([A-Z]\w*Screen)\b", source))


def _action_symbols(source: str) -> list[str]:
    return re.findall(r"function\s+([a-z]\w*)\b", source)
