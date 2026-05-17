# One-Command Installer + Landing Page — Design

Date: 2026-05-16
Status: Approved (pending spec review)

## Goal

A user, standing inside their iOS app's git repo, runs a single
copy-pasted command from a brew.sh-style landing page. With no further
input beyond one API-key paste, the tool installs itself, auto-detects
the app/simulator target, runs autonomous integration testing on the
iOS Simulator, and leaves a committable re-runner script in the repo.

## Chosen Approach

**Bootstrap installer + repo-local re-runner** (Approach A). The hosted
`curl … | bash` one-liner both runs immediately against the current
repo and writes a small `./ios-test` script into that repo so teammates
can re-run without the curl bootstrap. Rejected: pure global CLI (no
in-repo artifact, fails the brief); single vendored fat script (the
engine is a real Python package, cannot be inlined into bash).

## Hosting

GitHub + GitHub Pages. A single placeholder constant pair `OWNER` /
`REPO` is used everywhere a URL is needed, filled in once before launch.

- Engine repo: `https://github.com/OWNER/REPO`
- Landing page: `https://OWNER.github.io/REPO/`
- Install script: `https://OWNER.github.io/REPO/install.sh`

## The One Command

```
curl -fsSL https://OWNER.github.io/REPO/install.sh | bash
```

## Artifacts

| Path | Purpose |
|------|---------|
| `web/index.html` | brew.sh-style landing page. DESIGN.md palette (`#0A0E14` bg, phosphor mint `#5EF6A4`, dim slate `#5A6B7A`), JetBrains Mono, hero = the single copy-paste command with a copy button. Static, served by GitHub Pages. |
| `install.sh` | The bootstrap script, served from GitHub Pages root. |
| `web/ios-test.template` | Template for the re-runner the installer writes into the user's repo as executable `./ios-test`. |
| `web/README.md` | One-paragraph note on filling `OWNER`/`REPO` and enabling Pages. |

`OWNER` and `REPO` appear as literal placeholder tokens in every
artifact; replacing them is the only pre-launch step.

## install.sh Flow

Strict mode: `set -euo pipefail`. All steps emit progress to stderr;
the engine's own Rich TUI owns stdout during the run.

1. **Preflight.** Assert each, exiting non-zero with the exact remedy
   on failure:
   - macOS (`uname` = Darwin).
   - `xcodebuild` present (`xcode-select -p` resolves).
   - `xcrun simctl` present.
   - `git` present.
   - `python3` ≥ 3.11 (`python3 -c 'import sys; assert sys.version_info >= (3,11)'`).
2. **Engine install/update.** Target dir `~/.ios-test` (override:
   `IOS_TEST_HOME`). If absent: `git clone --depth 1
   https://github.com/OWNER/REPO ~/.ios-test`. If present and a git
   repo: `git -C ~/.ios-test pull --ff-only`. Create venv
   `~/.ios-test/.venv` if missing; `~/.ios-test/.venv/bin/pip install
   -e ~/.ios-test`. Idempotent: re-running only pulls + reinstalls.
3. **Credentials.** Resolve `OPENAI_API_KEY` from environment, then
   from `./.env` in the current repo. If still unset and the shell is
   interactive (`[ -t 0 ]`): prompt with hidden input (`read -rs`),
   append to `./.env`, ensure `.env` is in the repo's `.gitignore`
   (append if missing, create `.gitignore` if absent). Also prompt
   (optional, may be empty) for `ANTHROPIC_API_KEY` because the gbrain
   expansion/chat models default to `anthropic:*` (see
   `scripts/ios-test-agent`). If not interactive and key missing:
   print instructions and exit non-zero (CI-safe, never hangs).
4. **Target auto-detection.** Working dir = the user's repo (cwd).
   - App path: cwd.
   - Project: find a single `*.xcworkspace` (preferred) or
     `*.xcodeproj` at repo root. If multiple, prompt to pick (numbered
     menu); non-interactive → error with the list.
   - Scheme: `xcodebuild -list -json`. One scheme → use it. Multiple →
     prompt; non-interactive → error.
   - Simulator: enumerate booted devices via `xcrun simctl list
     devices booted -j`. Exactly one booted → use it. None booted →
     boot the newest available iPhone runtime device and wait for
     boot. Multiple booted → prompt; non-interactive → first listed.
   - Build: `xcodebuild build` for the chosen scheme/sim destination
     into a derived-data path; locate the produced `*.app`; read
     `CFBundleIdentifier` from its `Info.plist` via `plutil`/`defaults`.
   - Each prompt has an env-var override
     (`IOS_TEST_SCHEME`, `IOS_TEST_UDID`, `IOS_TEST_BUNDLE_ID`,
     `IOS_TEST_PROJECT`) so the flow is fully scriptable.
5. **Run.** Invoke `~/.ios-test/.venv/bin/ios-test explore <app_path>
   --udid <udid> --bundle-id <bundle-id>`, with `.env` sourced and the
   gbrain runtime env exported the same way `scripts/ios-test-agent`
   does (`GBRAIN_HOME`, `GBRAIN_EXPANSION_MODEL`, `GBRAIN_CHAT_MODEL`).
   Engine exit code is propagated.
6. **Leave-behind.** Render `web/ios-test.template` into executable
   `./ios-test` in the user's repo (`chmod +x`). It re-runs steps 3–5
   only (no network, no clone) against `~/.ios-test`, with the same
   auto-detect + env-override behavior. Print a hint to commit it.

## Re-runner (`./ios-test`) Behavior

- Resolves `~/.ios-test` (or `IOS_TEST_HOME`); errors with the
  bootstrap one-liner if the engine is absent.
- Sources `./.env`, re-runs credential check (prompt only if
  interactive and missing), auto-detect, and the engine run.
- No `git clone`/`pip install` — fast path for repeat runs and CI.

## Error Handling

- `set -euo pipefail`; every external command existence-checked before
  first use with a remedy message.
- All interactive prompts gated on `[ -t 0 ]`; non-interactive contexts
  use env-var overrides or fail fast with actionable output — never
  block waiting on a TTY.
- `git pull` uses `--ff-only`; on divergence, instruct the user to
  remove `~/.ios-test` and re-run rather than auto-resetting.
- Partial install (clone ok, pip fails) is recoverable: re-running the
  one-liner resumes idempotently.

## Testing

- Shell tests (`bats` if available, else plain `bash` assertions under
  `tests/`) with a mocked `PATH` shimming `xcrun`, `xcodebuild`,
  `git`, `python3`:
  - Preflight detects each missing dependency and exits non-zero with
    the right message.
  - Target detection: single vs. multiple schemes; booted vs. none
    vs. multiple sims; env-var overrides bypass prompts.
  - Credential resolution precedence: env > `./.env` > prompt; `.env`
    gets gitignored; non-interactive missing key fails fast.
  - Leave-behind: `./ios-test` is generated, executable, syntactically
    valid (`bash -n`), and contains no unresolved template tokens.
- One offline smoke test: run `install.sh` end-to-end with all
  externals mocked and assert it reaches the engine-invocation step
  with correct args (engine itself stubbed).
- No test touches a real simulator, network, or API.

## Out of Scope (YAGNI)

- Linux support / Homebrew formula / `apt` packaging.
- Hosted proxy API key (rejected during brainstorming).
- Automated GitHub release publishing or versioned tarballs (engine is
  tracked by `git pull` of `main`).
- Self-update beyond `git pull --ff-only`.
- Multi-repo / monorepo target selection beyond the single-project +
  prompt fallback described above.

## Open Questions

None. `OWNER`/`REPO` are intentional placeholders, not unknowns.
