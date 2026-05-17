# One-Command Installer + Landing Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a brew.sh-style landing page whose single `curl … | bash` command installs the `ios-test` engine, auto-detects the iOS app/simulator target, runs autonomous integration testing, and leaves a committable `./ios-test` re-runner in the user's repo.

**Architecture:** One bash bootstrap (`install.sh`) written as a sourceable library of pure functions plus a `main` that runs only when executed directly — so each function is unit-testable via `pytest` shelling out with a mocked `PATH`. A static `web/index.html` hosts the command on GitHub Pages. A `web/ios-test.template` is rendered into the user's repo as the no-network re-runner.

**Tech Stack:** Bash (`set -euo pipefail`), `xcrun simctl`, `xcodebuild`, `plutil`, Python ≥3.11 venv, existing `ios-test` CLI (`ios-test explore <app> --udid --bundle-id`), pytest for the test harness, static HTML/CSS (DESIGN.md palette, JetBrains Mono).

**Placeholders:** The literal tokens `OWNER` and `REPO` appear in `install.sh`, `web/index.html`, and `web/ios-test.template`. They are intentional and replaced once before launch — not TODOs.

---

## File Structure

- Create: `install.sh` — bootstrap; sourceable function library + guarded `main`.
- Create: `web/index.html` — landing page, static.
- Create: `web/ios-test.template` — rendered into user repos as `./ios-test`.
- Create: `web/README.md` — pre-launch instructions (fill `OWNER`/`REPO`, enable Pages).
- Create: `tests/test_installer.py` — pytest harness driving `install.sh` with mocked binaries on `PATH`.
- Create: `tests/installer_fixtures/` — mock binary scripts (`xcodebuild`, `xcrun`, `git`, `python3`).

---

## Task 1: Installer skeleton — sourceable library with guarded main

**Files:**
- Create: `install.sh`
- Test: `tests/test_installer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_installer.py
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO / "install.sh"


def _source_and_call(func_call: str, env: dict, cwd: Path) -> subprocess.CompletedProcess:
    """Source install.sh as a library (no main) and run one function."""
    script = f'IOS_TEST_INSTALLER_LIB=1 source "{INSTALL_SH}"\n{func_call}\n'
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True, text=True, env=env, cwd=cwd,
    )


def test_install_sh_is_sourceable_without_running_main(tmp_path):
    import os
    env = {**os.environ, "PATH": "/usr/bin:/bin"}
    cp = _source_and_call('echo SOURCED_OK', env, tmp_path)
    assert cp.returncode == 0, cp.stderr
    assert "SOURCED_OK" in cp.stdout
    # main must NOT have run (no preflight output) when sourced as a lib
    assert "Preflight" not in cp.stdout and "Preflight" not in cp.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_installer.py::test_install_sh_is_sourceable_without_running_main -v`
Expected: FAIL — `install.sh` does not exist (`No such file`).

- [ ] **Step 3: Write minimal implementation**

```bash
#!/usr/bin/env bash
# install.sh — one-command installer for ios-test.
# Hosted at https://OWNER.github.io/REPO/install.sh
set -euo pipefail

IOS_TEST_REPO_URL="https://github.com/OWNER/REPO"
IOS_TEST_HOME_DEFAULT="$HOME/.ios-test"
BOOTSTRAP_CMD="curl -fsSL https://OWNER.github.io/REPO/install.sh | bash"

log()  { printf '\033[38;2;94;246;164m▸\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[38;2;255;107;94m!\033[0m %s\n' "$*" >&2; }
die()  { warn "$*"; exit 1; }

main() {
  log "Preflight"
  preflight
  local home; home="$(engine_install)"
  ensure_credentials
  local app udid bundle
  read -r app udid bundle < <(detect_target)
  run_engine "$home" "$app" "$udid" "$bundle"
  write_rerunner
  log "Done. Committable ./ios-test written to this repo."
}

# Defined in later tasks; stubbed so the library sources cleanly.
preflight()          { :; }
engine_install()     { echo "$IOS_TEST_HOME_DEFAULT"; }
ensure_credentials() { :; }
detect_target()      { echo ". UDID BUNDLE"; }
run_engine()         { :; }
write_rerunner()     { :; }

if [[ "${IOS_TEST_INSTALLER_LIB:-}" != "1" ]]; then
  main "$@"
fi
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_installer.py::test_install_sh_is_sourceable_without_running_main -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
chmod +x install.sh
git add install.sh tests/test_installer.py
git commit -m "feat(installer): sourceable skeleton with guarded main"
```

---

## Task 2: Mock binary fixtures + PATH harness

**Files:**
- Create: `tests/installer_fixtures/make_path.py`
- Test: `tests/test_installer.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_installer.py
import os, sys

sys.path.insert(0, str(REPO / "tests" / "installer_fixtures"))


def test_mock_path_provides_fake_tools(tmp_path):
    from make_path import make_path
    bindir = make_path(tmp_path, {
        "uname": 'echo Darwin',
        "git": 'echo git "$@"',
    })
    env = {**os.environ, "PATH": f"{bindir}:/usr/bin:/bin"}
    cp = subprocess.run(["bash", "-c", "uname; git clone X"],
                        capture_output=True, text=True, env=env)
    assert cp.stdout.splitlines() == ["Darwin", "git clone X"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_installer.py::test_mock_path_provides_fake_tools -v`
Expected: FAIL — `ModuleNotFoundError: make_path`.

- [ ] **Step 3: Write minimal implementation**

```python
# tests/installer_fixtures/make_path.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_installer.py::test_mock_path_provides_fake_tools -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/installer_fixtures/make_path.py tests/test_installer.py
git commit -m "test(installer): mock PATH harness"
```

---

## Task 3: `preflight` — dependency assertions

**Files:**
- Modify: `install.sh` (replace `preflight() { :; }`)
- Test: `tests/test_installer.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_installer.py
from make_path import make_path

GOOD_TOOLS = {
    "uname": 'echo Darwin',
    "xcode-select": 'echo /Applications/Xcode.app',
    "xcrun": 'exit 0',
    "git": 'exit 0',
    "python3": 'exit 0',
}


def _run_func(func, tools, tmp_path, extra_env=None):
    bindir = make_path(tmp_path, tools)
    env = {**os.environ, "PATH": f"{bindir}:/usr/bin:/bin", **(extra_env or {})}
    return _source_and_call(func, env, tmp_path)


def test_preflight_passes_when_all_present(tmp_path):
    cp = _run_func("preflight && echo PREFLIGHT_OK", GOOD_TOOLS, tmp_path)
    assert cp.returncode == 0, cp.stderr
    assert "PREFLIGHT_OK" in cp.stdout


def test_preflight_fails_without_git(tmp_path):
    tools = {k: v for k, v in GOOD_TOOLS.items() if k != "git"}
    cp = _run_func("preflight", tools, tmp_path)
    assert cp.returncode != 0
    assert "git" in cp.stderr.lower()


def test_preflight_fails_on_non_macos(tmp_path):
    tools = {**GOOD_TOOLS, "uname": 'echo Linux'}
    cp = _run_func("preflight", tools, tmp_path)
    assert cp.returncode != 0
    assert "macos" in cp.stderr.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_installer.py -k preflight -v`
Expected: FAIL — stub `preflight` is a no-op, so `test_preflight_fails_without_git` and `test_preflight_fails_on_non_macos` fail (returncode 0).

- [ ] **Step 3: Write minimal implementation**

Replace `preflight()          { :; }` in `install.sh` with:

```bash
preflight() {
  [[ "$(uname -s 2>/dev/null)" == "Darwin" ]] \
    || die "This tool runs on macOS only (needs the iOS Simulator)."
  command -v xcode-select >/dev/null 2>&1 && xcode-select -p >/dev/null 2>&1 \
    || die "Xcode command-line tools missing. Run: xcode-select --install"
  command -v xcrun >/dev/null 2>&1 \
    || die "xcrun not found. Install Xcode from the App Store."
  command -v git >/dev/null 2>&1 \
    || die "git not found. Install git, then re-run: $BOOTSTRAP_CMD"
  command -v python3 >/dev/null 2>&1 \
    || die "python3 not found. Install Python 3.11+ (e.g. brew install python@3.12)."
  python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)' \
    || die "Python 3.11+ required. Found: $(python3 --version 2>&1)"
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_installer.py -k preflight -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add install.sh tests/test_installer.py
git commit -m "feat(installer): preflight dependency checks"
```

---

## Task 4: `engine_install` — clone/update + venv

**Files:**
- Modify: `install.sh` (replace `engine_install() { ... }`)
- Test: `tests/test_installer.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_installer.py
def test_engine_install_clones_when_absent(tmp_path):
    home = tmp_path / "engine"
    tools = {
        **GOOD_TOOLS,
        # git clone <url> <dest> -> create dest with a .git marker
        "git": 'if [[ "$1" == clone ]]; then mkdir -p "${@: -1}/.git"; '
               'elif [[ "$1" == -C ]]; then exit 0; fi',
        # python3 -m venv <dir> -> make dir/bin/pip and dir/bin/ios-test
        "python3": 'if [[ "$1" == -m && "$2" == venv ]]; then '
                   'mkdir -p "$3/bin"; printf "#!/bin/sh\\nexit 0\\n" > "$3/bin/pip"; '
                   'chmod +x "$3/bin/pip"; printf "#!/bin/sh\\nexit 0\\n" > "$3/bin/ios-test"; '
                   'chmod +x "$3/bin/ios-test"; fi',
    }
    cp = _run_func('engine_install', tools, tmp_path,
                   extra_env={"IOS_TEST_HOME": str(home)})
    assert cp.returncode == 0, cp.stderr
    assert cp.stdout.strip().endswith(str(home))
    assert (home / ".git").is_dir()
    assert (home / ".venv" / "bin" / "pip").exists()


def test_engine_install_pulls_when_present(tmp_path):
    home = tmp_path / "engine"
    (home / ".git").mkdir(parents=True)
    (home / ".venv" / "bin").mkdir(parents=True)
    (home / ".venv" / "bin" / "pip").write_text("#!/bin/sh\nexit 0\n")
    (home / ".venv" / "bin" / "pip").chmod(0o755)
    marker = home / "pulled"
    tools = {
        **GOOD_TOOLS,
        "git": f'if [[ "$1" == -C && "$3" == pull ]]; then touch "{marker}"; fi',
        "python3": 'exit 0',
    }
    cp = _run_func('engine_install', tools, tmp_path,
                   extra_env={"IOS_TEST_HOME": str(home)})
    assert cp.returncode == 0, cp.stderr
    assert marker.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_installer.py -k engine_install -v`
Expected: FAIL — stub returns home but never creates `.git`/`.venv` or pulls.

- [ ] **Step 3: Write minimal implementation**

Replace `engine_install()     { echo "$IOS_TEST_HOME_DEFAULT"; }` with:

```bash
engine_install() {
  local home="${IOS_TEST_HOME:-$IOS_TEST_HOME_DEFAULT}"
  if [[ -d "$home/.git" ]]; then
    log "Updating engine in $home"
    git -C "$home" pull --ff-only >&2 \
      || die "Engine update failed (diverged). Remove $home and re-run."
  else
    log "Cloning engine to $home"
    rm -rf "$home"
    git clone --depth 1 "$IOS_TEST_REPO_URL" "$home" >&2 \
      || die "git clone failed from $IOS_TEST_REPO_URL"
  fi
  if [[ ! -x "$home/.venv/bin/pip" ]]; then
    log "Creating virtualenv"
    python3 -m venv "$home/.venv" >&2 || die "venv creation failed"
  fi
  log "Installing engine dependencies"
  "$home/.venv/bin/pip" install -q -e "$home" >&2 \
    || die "pip install failed in $home"
  echo "$home"
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_installer.py -k engine_install -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add install.sh tests/test_installer.py
git commit -m "feat(installer): clone/update engine + venv"
```

---

## Task 5: `ensure_credentials` — env > .env > prompt, gitignore .env

**Files:**
- Modify: `install.sh` (replace `ensure_credentials() { :; }`)
- Test: `tests/test_installer.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_installer.py
def test_credentials_noop_when_env_set(tmp_path):
    cp = _run_func('ensure_credentials && echo CREDS_OK', GOOD_TOOLS, tmp_path,
                    extra_env={"OPENAI_API_KEY": "sk-live"})
    assert cp.returncode == 0, cp.stderr
    assert "CREDS_OK" in cp.stdout
    assert not (tmp_path / ".env").exists()  # nothing written when already set


def test_credentials_read_from_dotenv(tmp_path):
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-fromfile\n")
    env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
    cp = _run_func('ensure_credentials && echo "K=$OPENAI_API_KEY"',
                    GOOD_TOOLS, tmp_path, extra_env={**env, "OPENAI_API_KEY": ""})
    assert cp.returncode == 0, cp.stderr
    assert "K=sk-fromfile" in cp.stdout


def test_credentials_fail_fast_when_noninteractive_and_missing(tmp_path):
    env = {**os.environ}
    env.pop("OPENAI_API_KEY", None)
    cp = _run_func('ensure_credentials < /dev/null', GOOD_TOOLS, tmp_path,
                    extra_env={**env, "OPENAI_API_KEY": ""})
    assert cp.returncode != 0
    assert "OPENAI_API_KEY" in cp.stderr


def test_credentials_prompt_writes_and_gitignores(tmp_path):
    env = {**os.environ}
    env.pop("OPENAI_API_KEY", None)
    # Simulate interactive: feed key then empty Anthropic line; force TTY-ish
    cp = _run_func(
        'IOS_TEST_FORCE_INTERACTIVE=1 ensure_credentials',
        GOOD_TOOLS, tmp_path,
        extra_env={**env, "OPENAI_API_KEY": "",
                   "IOS_TEST_FAKE_STDIN": "sk-typed\n\n"})
    assert cp.returncode == 0, cp.stderr
    assert "OPENAI_API_KEY=sk-typed" in (tmp_path / ".env").read_text()
    assert ".env" in (tmp_path / ".gitignore").read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_installer.py -k credentials -v`
Expected: FAIL — stub is a no-op; dotenv read, fail-fast, and prompt all unimplemented.

- [ ] **Step 3: Write minimal implementation**

Replace `ensure_credentials() { :; }` with:

```bash
_load_dotenv() {
  [[ -f .env ]] || return 0
  set -a; # shellcheck disable=SC1091
  source ./.env; set +a
}

_gitignore_env() {
  touch .gitignore
  grep -qxF '.env' .gitignore || printf '\n.env\n' >> .gitignore
}

_prompt_secret() {  # $1=label  -> echoes value
  local v
  if [[ -n "${IOS_TEST_FAKE_STDIN:-}" ]]; then
    v="$(printf '%s' "$IOS_TEST_FAKE_STDIN" | head -n1)"
    IOS_TEST_FAKE_STDIN="$(printf '%s' "$IOS_TEST_FAKE_STDIN" | tail -n +2)"
  else
    read -rs -p "$1: " v >&2; echo >&2
  fi
  printf '%s' "$v"
}

_is_interactive() { [[ -n "${IOS_TEST_FORCE_INTERACTIVE:-}" || -t 0 ]]; }

ensure_credentials() {
  [[ -n "${OPENAI_API_KEY:-}" ]] || _load_dotenv
  if [[ -z "${OPENAI_API_KEY:-}" ]]; then
    if _is_interactive; then
      local key; key="$(_prompt_secret 'Paste your OPENAI_API_KEY')"
      [[ -n "$key" ]] || die "No OPENAI_API_KEY provided."
      _gitignore_env
      printf 'OPENAI_API_KEY=%s\n' "$key" >> .env
      export OPENAI_API_KEY="$key"
      local ak; ak="$(_prompt_secret 'Optional ANTHROPIC_API_KEY (Enter to skip)')"
      if [[ -n "$ak" ]]; then
        printf 'ANTHROPIC_API_KEY=%s\n' "$ak" >> .env
        export ANTHROPIC_API_KEY="$ak"
      fi
    else
      die "OPENAI_API_KEY is required. Export it or add it to ./.env, then re-run."
    fi
  fi
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_installer.py -k credentials -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add install.sh tests/test_installer.py
git commit -m "feat(installer): credential resolution + .env gitignore"
```

---

## Task 6: `detect_target` — project/scheme/sim/bundle with overrides

**Files:**
- Modify: `install.sh` (replace `detect_target() { ... }`)
- Test: `tests/test_installer.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_installer.py
def test_detect_target_uses_env_overrides(tmp_path):
    cp = _run_func('detect_target', GOOD_TOOLS, tmp_path, extra_env={
        "IOS_TEST_UDID": "UDID-123",
        "IOS_TEST_BUNDLE_ID": "com.acme.app",
    })
    assert cp.returncode == 0, cp.stderr
    app, udid, bundle = cp.stdout.strip().split()
    assert udid == "UDID-123"
    assert bundle == "com.acme.app"
    assert Path(app).resolve() == tmp_path.resolve()


def test_detect_target_errors_noninteractive_multiple_schemes(tmp_path):
    (tmp_path / "App.xcodeproj").mkdir()
    tools = {
        **GOOD_TOOLS,
        "xcodebuild": 'echo \'{"project":{"schemes":["A","B"]}}\'',
    }
    cp = _run_func('detect_target < /dev/null', tools, tmp_path)
    assert cp.returncode != 0
    assert "scheme" in cp.stderr.lower()


def test_detect_target_picks_single_booted_sim(tmp_path):
    (tmp_path / "App.xcodeproj").mkdir()
    tools = {
        **GOOD_TOOLS,
        "xcodebuild": 'echo \'{"project":{"schemes":["Only"]}}\'',
        "xcrun": 'if [[ "$1" == simctl && "$2" == list ]]; then '
                 'echo \'{"devices":{"iOS":[{"udid":"BOOT-1","state":"Booted","name":"iPhone 15"}]}}\'; fi',
    }
    cp = _run_func('detect_target', tools, tmp_path,
                   extra_env={"IOS_TEST_BUNDLE_ID": "com.x"})
    assert cp.returncode == 0, cp.stderr
    _, udid, _ = cp.stdout.strip().split()
    assert udid == "BOOT-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_installer.py -k detect_target -v`
Expected: FAIL — stub echoes `. UDID BUNDLE` regardless of overrides/inputs.

- [ ] **Step 3: Write minimal implementation**

Replace `detect_target()      { echo ". UDID BUNDLE"; }` with:

```bash
_detect_scheme() {
  [[ -n "${IOS_TEST_SCHEME:-}" ]] && { echo "$IOS_TEST_SCHEME"; return; }
  local schemes
  schemes="$(xcodebuild -list -json 2>/dev/null \
    | python3 -c 'import sys,json; d=json.load(sys.stdin); \
print("\n".join((d.get("project") or d.get("workspace") or {}).get("schemes",[])))' \
    2>/dev/null || true)"
  local n; n="$(printf '%s\n' "$schemes" | grep -c . || true)"
  if [[ "$n" -eq 1 ]]; then printf '%s' "$schemes"
  elif [[ "$n" -eq 0 ]]; then die "No Xcode schemes found in $(pwd)."
  elif _is_interactive; then
    echo "Multiple schemes:" >&2; printf '%s\n' "$schemes" | nl -w2 -s') ' >&2
    local i; i="$(_prompt_secret 'Scheme number')"
    printf '%s' "$schemes" | sed -n "${i}p"
  else
    die "Multiple schemes; set IOS_TEST_SCHEME. Found: $(echo $schemes)"
  fi
}

_detect_udid() {
  [[ -n "${IOS_TEST_UDID:-}" ]] && { echo "$IOS_TEST_UDID"; return; }
  local booted
  booted="$(xcrun simctl list devices booted -j 2>/dev/null \
    | python3 -c 'import sys,json; d=json.load(sys.stdin); \
print("\n".join(x["udid"] for v in d.get("devices",{}).values() for x in v if x.get("state")=="Booted"))' \
    2>/dev/null || true)"
  local n; n="$(printf '%s\n' "$booted" | grep -c . || true)"
  if [[ "$n" -ge 1 ]]; then printf '%s\n' "$booted" | head -n1
  else
    log "No booted simulator; booting default iPhone"
    local dev
    dev="$(xcrun simctl list devices available -j 2>/dev/null \
      | python3 -c 'import sys,json; d=json.load(sys.stdin); \
c=[x["udid"] for v in d.get("devices",{}).values() for x in v if "iPhone" in x.get("name","")]; \
print(c[-1] if c else "")' 2>/dev/null || true)"
    [[ -n "$dev" ]] || die "No available iPhone simulator. Create one in Xcode."
    xcrun simctl boot "$dev" >&2 || true
    printf '%s' "$dev"
  fi
}

_detect_bundle() {  # $1=scheme  $2=udid
  [[ -n "${IOS_TEST_BUNDLE_ID:-}" ]] && { echo "$IOS_TEST_BUNDLE_ID"; return; }
  local dd; dd="$(mktemp -d)"
  log "Building $1 (first run only)"
  xcodebuild -scheme "$1" -destination "id=$2" \
    -derivedDataPath "$dd" build >&2 || die "xcodebuild build failed for $1"
  local app; app="$(find "$dd/Build/Products" -maxdepth 2 -name '*.app' | head -n1)"
  [[ -n "$app" ]] || die "Built .app not found under $dd"
  plutil -extract CFBundleIdentifier raw "$app/Info.plist" 2>/dev/null \
    || die "Could not read CFBundleIdentifier from $app/Info.plist"
}

detect_target() {
  ls *.xcworkspace *.xcodeproj >/dev/null 2>&1 \
    || die "No .xcworkspace/.xcodeproj here. Run this from your iOS app repo root."
  local app scheme udid bundle
  app="$(pwd)"
  scheme="$(_detect_scheme)"
  udid="$(_detect_udid)"
  bundle="$(_detect_bundle "$scheme" "$udid")"
  echo "$app $udid $bundle"
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_installer.py -k detect_target -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add install.sh tests/test_installer.py
git commit -m "feat(installer): auto-detect scheme/sim/bundle with overrides"
```

---

## Task 7: `run_engine` + `write_rerunner`

**Files:**
- Modify: `install.sh` (replace `run_engine`/`write_rerunner` stubs)
- Create: `web/ios-test.template`
- Test: `tests/test_installer.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_installer.py
def test_run_engine_invokes_cli_with_args(tmp_path):
    home = tmp_path / "engine"
    (home / ".venv" / "bin").mkdir(parents=True)
    rec = home / "called.txt"
    iostest = home / ".venv" / "bin" / "ios-test"
    iostest.write_text(f'#!/bin/sh\necho "$@" > "{rec}"\n')
    iostest.chmod(0o755)
    cp = _run_func(f'run_engine "{home}" "/app" "UDID9" "com.z"',
                   GOOD_TOOLS, tmp_path)
    assert cp.returncode == 0, cp.stderr
    assert rec.read_text().strip() == "explore /app --udid UDID9 --bundle-id com.z"


def test_write_rerunner_emits_executable_valid_script(tmp_path):
    cp = _run_func('write_rerunner', GOOD_TOOLS, tmp_path)
    assert cp.returncode == 0, cp.stderr
    rr = tmp_path / "ios-test"
    assert rr.exists() and os.access(rr, os.X_OK)
    # Valid bash and no unresolved template tokens
    syn = subprocess.run(["bash", "-n", str(rr)], capture_output=True, text=True)
    assert syn.returncode == 0, syn.stderr
    body = rr.read_text()
    assert "{{" not in body and "}}" not in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_installer.py -k "run_engine or rerunner" -v`
Expected: FAIL — stubs do nothing; `web/ios-test.template` missing.

- [ ] **Step 3: Write minimal implementation**

Create `web/ios-test.template`:

```bash
#!/usr/bin/env bash
# ios-test — committable re-runner. Fast path: no clone, no pip.
# Regenerate via: {{BOOTSTRAP_CMD}}
set -euo pipefail
HOME_DIR="${IOS_TEST_HOME:-$HOME/.ios-test}"
[[ -x "$HOME_DIR/.venv/bin/ios-test" ]] || {
  echo "ios-test engine not installed. Run:" >&2
  echo "  {{BOOTSTRAP_CMD}}" >&2
  exit 1
}
LIB="$HOME_DIR/install.sh"
[[ -f "$LIB" ]] || { echo "Missing $LIB; re-run the installer." >&2; exit 1; }
IOS_TEST_INSTALLER_LIB=1 source "$LIB"
ensure_credentials
read -r APP UDID BUNDLE < <(detect_target)
run_engine "$HOME_DIR" "$APP" "$UDID" "$BUNDLE"
```

Replace the `run_engine`/`write_rerunner` stubs in `install.sh` with:

```bash
run_engine() {  # $1=home $2=app $3=udid $4=bundle
  local home="$1" app="$2" udid="$3" bundle="$4"
  log "Running ios-test on $bundle (sim $udid)"
  ( cd "$app" \
    && "$home/.venv/bin/ios-test" explore "$app" \
         --udid "$udid" --bundle-id "$bundle" )
}

write_rerunner() {
  local home="${IOS_TEST_HOME:-$IOS_TEST_HOME_DEFAULT}"
  local tpl="$home/web/ios-test.template"
  [[ -f "$tpl" ]] || tpl="$(dirname "${BASH_SOURCE[0]}")/web/ios-test.template"
  [[ -f "$tpl" ]] || die "ios-test.template not found (engine repo incomplete)."
  sed "s|{{BOOTSTRAP_CMD}}|$BOOTSTRAP_CMD|g" "$tpl" > ./ios-test
  chmod +x ./ios-test
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_installer.py -k "run_engine or rerunner" -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
chmod +x web/ios-test.template
git add install.sh web/ios-test.template tests/test_installer.py
git commit -m "feat(installer): engine run + committable re-runner"
```

---

## Task 8: End-to-end offline smoke test

**Files:**
- Test: `tests/test_installer.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_installer.py
def test_full_install_sh_reaches_engine_offline(tmp_path):
    repo = tmp_path / "myapp"; repo.mkdir()
    (repo / "App.xcodeproj").mkdir()
    home = tmp_path / "engine"
    (home / "web").mkdir(parents=True)
    (home / "web" / "ios-test.template").write_text(
        (REPO / "web" / "ios-test.template").read_text())
    rec = tmp_path / "engine_called.txt"
    tools = {
        "uname": 'echo Darwin',
        "xcode-select": 'echo /x', "xcrun": 'if [[ "$1" == simctl && "$2" == list ]]; then '
            'echo \'{"devices":{"iOS":[{"udid":"E2E","state":"Booted","name":"iPhone"}]}}\'; fi',
        "git": f'if [[ "$1" == clone ]]; then mkdir -p "{home}/.git"; '
               f'cp -R "{home}/web" "${{@: -1}}/web" 2>/dev/null || true; fi',
        "python3": 'if [[ "$1" == -m && "$2" == venv ]]; then mkdir -p "$3/bin"; '
                   'printf "#!/bin/sh\\nexit 0\\n">"$3/bin/pip"; chmod +x "$3/bin/pip"; '
                   f'printf "#!/bin/sh\\necho \\$@>{rec}\\n">"$3/bin/ios-test"; '
                   'chmod +x "$3/bin/ios-test"; '
                   'elif [[ "$1" == -c ]]; then python3.real "$@" 2>/dev/null || exit 0; fi',
        "xcodebuild": 'if [[ "$1" == -list ]]; then echo \'{"project":{"schemes":["S"]}}\'; fi',
        "plutil": 'echo com.e2e.app',
    }
    bindir = make_path(tmp_path, tools)
    env = {**os.environ, "PATH": f"{bindir}:/usr/bin:/bin",
           "IOS_TEST_HOME": str(home), "OPENAI_API_KEY": "sk-e2e",
           "IOS_TEST_BUNDLE_ID": "com.e2e.app"}
    cp = subprocess.run(["bash", str(INSTALL_SH)], capture_output=True,
                        text=True, env=env, cwd=repo)
    assert cp.returncode == 0, cp.stderr
    assert "explore" in rec.read_text()
    assert (repo / "ios-test").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_installer.py::test_full_install_sh_reaches_engine_offline -v`
Expected: FAIL initially if the clone mock doesn't seed `web/`; adjust only the mock (not `install.sh`) until green. Do not weaken `install.sh`.

- [ ] **Step 3: Make it pass**

Iterate on the test's mock binaries only until the assertions pass. `install.sh` must remain unchanged in this task (it is exercised, not modified).

- [ ] **Step 4: Run full installer suite**

Run: `.venv/bin/python -m pytest tests/test_installer.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_installer.py
git commit -m "test(installer): offline end-to-end smoke"
```

---

## Task 9: Landing page (brew.sh-style)

**Files:**
- Create: `web/index.html`
- Create: `web/README.md`
- Test: `tests/test_installer.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_installer.py
def test_landing_page_shows_the_one_command():
    html = (REPO / "web" / "index.html").read_text()
    assert "curl -fsSL https://OWNER.github.io/REPO/install.sh | bash" in html
    assert "#0A0E14" in html  # DESIGN.md background
    assert "#5EF6A4" in html  # phosphor mint
    assert "JetBrains Mono" in html


def test_web_readme_documents_placeholders():
    md = (REPO / "web" / "README.md").read_text()
    assert "OWNER" in md and "REPO" in md and "Pages" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_installer.py -k "landing or readme" -v`
Expected: FAIL — files missing.

- [ ] **Step 3: Write minimal implementation**

Create `web/index.html`:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ios-test — one command, autonomous iOS integration tests</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
  :root{--bg:#0A0E14;--mint:#5EF6A4;--active:#A8FFD0;--dim:#5A6B7A;--edge:#1C2530}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--active);font-family:"JetBrains Mono",monospace;
       min-height:100vh;display:flex;flex-direction:column;align-items:center;
       justify-content:center;padding:2rem;gap:2rem}
  h1{color:var(--mint);font-size:clamp(2rem,6vw,4rem);font-weight:700;letter-spacing:.04em}
  p.tag{color:var(--dim);font-size:1rem;text-align:center;max-width:42rem;line-height:1.6}
  .cmd{display:flex;align-items:center;gap:1rem;border:1px solid var(--edge);
       border-radius:10px;padding:1.1rem 1.4rem;background:#0d121b}
  .cmd code{color:var(--mint);font-size:clamp(.8rem,2.4vw,1.05rem);white-space:nowrap}
  button{font-family:inherit;background:transparent;border:1px solid var(--edge);
          color:var(--dim);border-radius:6px;padding:.45rem .8rem;cursor:pointer}
  button:hover{color:var(--mint);border-color:var(--mint)}
  footer{color:var(--dim);font-size:.85rem}
  a{color:var(--mint);text-decoration:none}
</style>
</head>
<body>
  <h1>ios-test</h1>
  <p class="tag">Autonomous integration testing for iOS apps. Run one command
     from your app's repo — it installs, detects your simulator target, and
     drives the tests itself.</p>
  <div class="cmd">
    <code id="c">curl -fsSL https://OWNER.github.io/REPO/install.sh | bash</code>
    <button onclick="navigator.clipboard.writeText(document.getElementById('c').textContent);this.textContent='copied'">copy</button>
  </div>
  <footer>macOS · Xcode · Python 3.11+ &nbsp;·&nbsp;
    <a href="https://github.com/OWNER/REPO">source</a></footer>
</body>
</html>
```

Create `web/README.md`:

```markdown
# Web / install assets

Before launch, replace the literal tokens `OWNER` and `REPO` in
`install.sh`, `web/index.html`, and `web/ios-test.template` with your
GitHub org/user and repository name.

## Enable hosting (GitHub Pages)

1. Push this repo to `https://github.com/OWNER/REPO` (public).
2. Repo Settings → Pages → Source: deploy from `main` / `/web` folder
   (or root if `install.sh` is copied into `/web`).
3. Ensure `install.sh` is reachable at
   `https://OWNER.github.io/REPO/install.sh` (copy or symlink it into the
   published folder if Pages serves `/web`).
4. The landing page is then live at `https://OWNER.github.io/REPO/`.

The one command users run:

    curl -fsSL https://OWNER.github.io/REPO/install.sh | bash
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_installer.py -k "landing or readme" -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add web/index.html web/README.md tests/test_installer.py
git commit -m "feat(web): brew.sh-style landing page + hosting README"
```

---

## Task 10: Full suite green + docs note

**Files:**
- Modify: `CLAUDE.md` (append a short "Installer" note)
- Test: all

- [ ] **Step 1: Run the entire test suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — existing suite plus all `tests/test_installer.py` cases.

- [ ] **Step 2: Lint the installer for syntax**

Run: `bash -n install.sh && bash -n web/ios-test.template && echo SYNTAX_OK`
Expected: `SYNTAX_OK`

- [ ] **Step 3: Append installer note to CLAUDE.md**

Add this section to the end of `CLAUDE.md`:

```markdown
## One-Command Installer
`install.sh` (sourceable lib + guarded `main`) and `web/` host the
brew.sh-style entrypoint. Tests: `tests/test_installer.py` (mocked PATH;
no real simulator/network). Replace `OWNER`/`REPO` placeholders before
launch — see `web/README.md`.
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: note one-command installer in CLAUDE.md"
```

---

## Self-Review

- **Spec coverage:** hosting/placeholders → Task 1,9; one command → Task 9;
  preflight → Task 3; engine clone/update+venv → Task 4; credentials
  precedence + gitignore + fail-fast → Task 5; auto-detect + overrides +
  prompt fallback → Task 6; run → Task 7; leave-behind re-runner → Task 7;
  error handling (`set -euo pipefail`, `die`, non-interactive guards) →
  Tasks 1,3,5,6; testing (mocked PATH unit + offline e2e, no real
  sim/net) → Tasks 2–8; landing page palette/font → Task 9; YAGNI items
  intentionally absent. No gaps.
- **Placeholder scan:** `OWNER`/`REPO`/`{{BOOTSTRAP_CMD}}` are deliberate,
  resolved by `sed` (Task 7) or documented (Task 9). No TODO/TBD steps;
  every code step shows full code.
- **Type/name consistency:** function names (`preflight`,
  `engine_install`, `ensure_credentials`, `detect_target`, `run_engine`,
  `write_rerunner`) and env vars (`IOS_TEST_HOME`, `IOS_TEST_UDID`,
  `IOS_TEST_BUNDLE_ID`, `IOS_TEST_SCHEME`, `IOS_TEST_FORCE_INTERACTIVE`,
  `IOS_TEST_FAKE_STDIN`) are used identically across all tasks. CLI call
  `ios-test explore <app> --udid --bundle-id` matches `src/cli.py`.
