"""Minimal .env loader for local CLI use.

Avoids adding another dependency just to read OPENAI_API_KEY during demos.
Existing environment variables win over .env values.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(start: str | Path | None = None) -> None:
    root = Path(start or Path.cwd()).resolve()
    for directory in (root, *root.parents):
        path = directory / ".env"
        if path.exists():
            _load_file(path)
            _default_gbrain_home(directory)
            return
    _default_gbrain_home(root)


def _load_file(path: Path) -> None:
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = _clean_value(value.strip())
        if key and key not in os.environ:
            os.environ[key] = value


def _clean_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _default_gbrain_home(root: Path) -> None:
    runtime = root / ".gbrain-runtime"
    wrapper = root / "scripts" / "gbrain-project"
    if "GBRAIN_HOME" not in os.environ and runtime.exists():
        os.environ["GBRAIN_HOME"] = str(runtime)
    if "GBRAIN_BIN" not in os.environ and wrapper.exists():
        os.environ["GBRAIN_BIN"] = str(wrapper)
        os.environ.setdefault("GBRAIN_TIMEOUT_S", "35")
    os.environ.setdefault("GBRAIN_EXPANSION_MODEL", "anthropic:claude-haiku-4-5-20251001")
    os.environ.setdefault("GBRAIN_CHAT_MODEL", "anthropic:claude-sonnet-4-6")
