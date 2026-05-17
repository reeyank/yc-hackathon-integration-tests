import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO / "install.sh"

sys.path.insert(0, str(REPO / "tests" / "installer_fixtures"))
from make_path import make_path  # noqa: E402


def _source_and_call(func_call: str, env: dict, cwd: Path) -> subprocess.CompletedProcess:
    """Source install.sh as a library (no main) and run one function."""
    script = f'IOS_TEST_INSTALLER_LIB=1 source "{INSTALL_SH}"\n{func_call}\n'
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True, text=True, env=env, cwd=cwd,
    )


GOOD_TOOLS = {
    "uname": 'echo Darwin',
    "xcode-select": 'echo /Applications/Xcode.app',
    "xcrun": 'exit 0',
    "git": 'exit 0',
    "python3": 'exit 0',
}


# python3 that answers preflight's version probe as >=3.11 but delegates
# all other -c invocations (JSON parsing) to the real interpreter.
PY_DELEGATE = (
    'if [[ "$1" == -c && "$2" == *version_info* ]]; then exit 0; '
    'elif [[ "$1" == -c ]]; then exec /usr/bin/python3 "$@"; '
    'else exec /usr/bin/python3 "$@"; fi'
)


def _run_func(func, tools, tmp_path, extra_env=None, isolated=False):
    bindir = make_path(tmp_path, tools)
    # isolated: /bin only (has bash, lacks git) so absence tests are real.
    path = f"{bindir}:/bin" if isolated else f"{bindir}:/usr/bin:/bin"
    env = {**os.environ, "PATH": path, **(extra_env or {})}
    return _source_and_call(func, env, tmp_path)


# --- Task 1 ---------------------------------------------------------------

def test_install_sh_is_sourceable_without_running_main(tmp_path):
    env = {**os.environ, "PATH": "/usr/bin:/bin"}
    cp = _source_and_call('echo SOURCED_OK', env, tmp_path)
    assert cp.returncode == 0, cp.stderr
    assert "SOURCED_OK" in cp.stdout
    assert "Preflight" not in cp.stdout and "Preflight" not in cp.stderr


# --- Task 2 ---------------------------------------------------------------

def test_mock_path_provides_fake_tools(tmp_path):
    bindir = make_path(tmp_path, {
        "uname": 'echo Darwin',
        "git": 'echo git "$@"',
    })
    env = {**os.environ, "PATH": f"{bindir}:/usr/bin:/bin"}
    cp = subprocess.run(["bash", "-c", "uname; git clone X"],
                        capture_output=True, text=True, env=env)
    assert cp.stdout.splitlines() == ["Darwin", "git clone X"]


# --- Task 3: preflight ----------------------------------------------------

def test_preflight_passes_when_all_present(tmp_path):
    cp = _run_func("preflight && echo PREFLIGHT_OK", GOOD_TOOLS, tmp_path)
    assert cp.returncode == 0, cp.stderr
    assert "PREFLIGHT_OK" in cp.stdout


def test_preflight_fails_without_git(tmp_path):
    tools = {k: v for k, v in GOOD_TOOLS.items() if k != "git"}
    cp = _run_func("preflight", tools, tmp_path, isolated=True)
    assert cp.returncode != 0
    assert "git" in cp.stderr.lower()


def test_preflight_fails_on_non_macos(tmp_path):
    tools = {**GOOD_TOOLS, "uname": 'echo Linux'}
    cp = _run_func("preflight", tools, tmp_path)
    assert cp.returncode != 0
    assert "macos" in cp.stderr.lower()


# --- Task 4: engine_install ----------------------------------------------

def test_engine_install_clones_when_absent(tmp_path):
    home = tmp_path / "engine"
    tools = {
        **GOOD_TOOLS,
        "git": 'if [[ "$1" == clone ]]; then mkdir -p "${@: -1}/.git"; '
               'elif [[ "$1" == -C ]]; then exit 0; fi',
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


# --- Task 5: credentials --------------------------------------------------

def test_credentials_noop_when_env_set(tmp_path):
    cp = _run_func('ensure_credentials && echo CREDS_OK', GOOD_TOOLS, tmp_path,
                    extra_env={"OPENAI_API_KEY": "sk-live"})
    assert cp.returncode == 0, cp.stderr
    assert "CREDS_OK" in cp.stdout
    assert not (tmp_path / ".env").exists()


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
    cp = _run_func(
        'IOS_TEST_FORCE_INTERACTIVE=1 ensure_credentials',
        GOOD_TOOLS, tmp_path,
        extra_env={**env, "OPENAI_API_KEY": "",
                   "IOS_TEST_FAKE_STDIN": "sk-typed\n\n"})
    assert cp.returncode == 0, cp.stderr
    assert "OPENAI_API_KEY=sk-typed" in (tmp_path / ".env").read_text()
    assert ".env" in (tmp_path / ".gitignore").read_text()


# --- Task 6: detect_target ------------------------------------------------

def test_detect_target_uses_env_overrides(tmp_path):
    (tmp_path / "App.xcodeproj").mkdir()
    cp = _run_func('detect_target', GOOD_TOOLS, tmp_path, extra_env={
        "IOS_TEST_UDID": "UDID-123",
        "IOS_TEST_BUNDLE_ID": "com.acme.app",
        "IOS_TEST_SCHEME": "Acme",
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
        "python3": PY_DELEGATE,
        "xcodebuild": 'echo \'{"project":{"schemes":["A","B"]}}\'',
    }
    cp = _run_func('detect_target < /dev/null', tools, tmp_path)
    assert cp.returncode != 0
    assert "scheme" in cp.stderr.lower()


def test_detect_target_picks_single_booted_sim(tmp_path):
    (tmp_path / "App.xcodeproj").mkdir()
    tools = {
        **GOOD_TOOLS,
        "python3": PY_DELEGATE,
        "xcodebuild": 'echo \'{"project":{"schemes":["Only"]}}\'',
        "xcrun": 'if [[ "$1" == simctl && "$2" == list ]]; then '
                 'echo \'{"devices":{"iOS":[{"udid":"BOOT-1","state":"Booted","name":"iPhone 15"}]}}\'; fi',
    }
    cp = _run_func('detect_target', tools, tmp_path,
                   extra_env={"IOS_TEST_BUNDLE_ID": "com.x"})
    assert cp.returncode == 0, cp.stderr
    _, udid, _ = cp.stdout.strip().split()
    assert udid == "BOOT-1"


# --- Task 7: run_engine + write_rerunner ----------------------------------

def test_run_engine_invokes_cli_with_args(tmp_path):
    home = tmp_path / "engine"
    (home / ".venv" / "bin").mkdir(parents=True)
    rec = home / "called.txt"
    iostest = home / ".venv" / "bin" / "ios-test"
    iostest.write_text(f'#!/bin/sh\necho "$@" > "{rec}"\n')
    iostest.chmod(0o755)
    app = tmp_path / "app"; app.mkdir()
    cp = _run_func(f'run_engine "{home}" "{app}" "UDID9" "com.z"',
                   GOOD_TOOLS, tmp_path)
    assert cp.returncode == 0, cp.stderr
    assert rec.read_text().strip() == f"explore {app} --udid UDID9 --bundle-id com.z"


def test_write_rerunner_emits_executable_valid_script(tmp_path):
    cp = _run_func('write_rerunner', GOOD_TOOLS, tmp_path)
    assert cp.returncode == 0, cp.stderr
    rr = tmp_path / "ios-test"
    assert rr.exists() and os.access(rr, os.X_OK)
    syn = subprocess.run(["bash", "-n", str(rr)], capture_output=True, text=True)
    assert syn.returncode == 0, syn.stderr
    body = rr.read_text()
    assert "{{" not in body and "}}" not in body


# --- Task 8: offline end-to-end -------------------------------------------

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
        "xcode-select": 'echo /x',
        "xcrun": 'if [[ "$1" == simctl && "$2" == list ]]; then '
                 'echo \'{"devices":{"iOS":[{"udid":"E2E","state":"Booted","name":"iPhone"}]}}\'; fi',
        "git": f'if [[ "$1" == clone ]]; then mkdir -p "{home}/.git"; fi',
        "python3": 'if [[ "$1" == -m && "$2" == venv ]]; then mkdir -p "$3/bin"; '
                   'printf "#!/bin/sh\\nexit 0\\n">"$3/bin/pip"; chmod +x "$3/bin/pip"; '
                   f'printf "#!/bin/sh\\necho \\$@>{rec}\\n">"$3/bin/ios-test"; '
                   'chmod +x "$3/bin/ios-test"; '
                   'elif [[ "$1" == -c && "$2" == *version_info* ]]; then exit 0; '
                   'else exec /usr/bin/python3 "$@"; fi',
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


# --- Task 9: landing page -------------------------------------------------

def test_landing_page_shows_the_one_command():
    html = (REPO / "web" / "index.html").read_text()
    assert "curl -fsSL https://OWNER.github.io/REPO/install.sh | bash" in html
    assert "#0A0E14" in html
    assert "#5EF6A4" in html
    assert "JetBrains Mono" in html


def test_web_readme_documents_placeholders():
    md = (REPO / "web" / "README.md").read_text()
    assert "OWNER" in md and "REPO" in md and "Pages" in md
