"""Build a directory of executable mock binaries for installer tests."""
from pathlib import Path


def make_path(tmp_path: Path, tools: dict[str, str]) -> Path:
    """tools maps binary name -> bash body. Returns the bin dir."""
    bindir = tmp_path / "mockbin"
    bindir.mkdir(parents=True, exist_ok=True)
    for name, body in tools.items():
        p = bindir / name
        p.write_text("#!/usr/bin/env bash\nset -e\n" + body + "\n")
        p.chmod(0o755)
    return bindir
