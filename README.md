# ios-test

**One-command autonomous integration testing for React Native iOS apps.**

Point it at an iOS app. An AI agent reads the source with semantic code
search, drives the live Simulator like a human QA tester, records every
tap and assertion into a replayable trace, and emits a real test suite —
plus a coverage map that *lights up* as the agent exercises your code.

```bash
curl -fsSL https://OWNER.github.io/REPO/install.sh | bash
```

> Replace `OWNER`/`REPO` with your GitHub org and repo before launch — see
> [`web/README.md`](web/README.md).

---

## Why

Integration tests for mobile apps are the tests nobody writes: brittle
selectors, hand-authored flows, and a Simulator that breaks them every
release. `ios-test` flips the model — the agent *discovers* the flows by
reading your code and exercising the app, then writes the tests for you.

- **gbrain-directed.** Flows aren't guessed from the UI tree. The agent
  queries [gbrain](https://github.com/) semantic search over your app's
  source to find auth, navigation, and key screens — then tests *those*.
- **Real Simulator, real signal.** Drives `idb`/`xcrun simctl` against a
  booted Simulator. No mocked UI, no headless approximation.
- **Replayable traces.** Every run produces a versioned `trace.json` you
  can re-run, diff, and code-gen from.
- **Live coverage map.** A bioluminescent terminal view where Swift/JS
  symbols ignite as the agent reaches them. See [`DESIGN.md`](DESIGN.md).

## How it works

```
 your iOS app  ──►  gbrain index   ──►  flow extractor  ──►  agent loop
 (.app + src)       (semantic         (auth / nav /        (OpenAI decides
                     code search)      key screens)         next action)
                                                                │
                                                                ▼
                          trace.json  ◄──  idb drives the booted Simulator
                                │
                ┌───────────────┼────────────────┐
                ▼               ▼                ▼
          codegen-detox     coverage.json    replay (assert)
          (.e2e.js suite)   (live map)       (regression gate)
```

1. **Index** — `gbrain-index` ingests app source into a worktree-scoped
   semantic source.
2. **Plan** — `flow_extractor` asks gbrain for evidence of real flows
   (login, signup, primary navigation) instead of blindly crawling.
3. **Explore / agent-run** — the agent loop drives the Simulator. The
   OpenAI decider picks the next action; `idb_wrapper` executes it; every
   step + assertion is appended to a `Trace`.
4. **Emit** — turn the trace into a Detox suite, a coverage map, or
   replay it as a pass/fail regression gate.

## Quick start

### One command (recommended)

Run from the root of your iOS app repo (the directory with a
`.xcworkspace`/`.xcodeproj`):

```bash
curl -fsSL https://OWNER.github.io/REPO/install.sh | bash
```

The installer runs preflight (macOS, Xcode CLT, Python 3.11+), clones the
engine to `~/.ios-test`, auto-detects scheme/UDID/bundle id, runs an
exploration pass, and drops a committable `./ios-test` re-runner into your
repo.

### Manual / development

```bash
git clone https://github.com/OWNER/REPO ios-test && cd ios-test
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # add your OPENAI_API_KEY
```

Boot a Simulator and grab its UDID:

```bash
xcrun simctl list devices booted
```

Then run the agent:

```bash
ios-test agent-run /path/to/YourApp.app \
  --udid <SIMULATOR_UDID> \
  --bundle-id com.your.bundle
```

## Commands

| Command | What it does |
|---|---|
| `agent-run <app>` | Full OpenAI + gbrain agent loop with a live TUI |
| `explore <app>` | Extract flows, drive the Simulator, write a trace |
| `gbrain-plan <app>` | Show the flow evidence gbrain found (no Simulator) |
| `gbrain-index <app>` | Index app source into gbrain pages |
| `check-trace <trace>` | Validate and summarize a `trace.json` |
| `codegen-detox <trace>` | Emit a Detox `.e2e.js` test from a trace |
| `coverage <trace>` | Emit `coverage/coverage.json` for the live map |
| `replay <trace>` | Re-run a trace; exit non-zero on assertion failure |

All app-facing commands accept `--gbrain-source`, `--fresh-gbrain`, and
`--skip-gbrain-sync`. Pass `--allow-local-fallback` to smoke-test without
gbrain (traces are marked `LOCAL_FALLBACK`).

Network capture: `agent-run --live-proxy` starts `mitmdump` and streams
request/response events into the TUI and trace.

## Requirements

- macOS with Xcode + command-line tools (`xcrun`, `simctl`)
- Python 3.11+
- An OpenAI API key (`OPENAI_API_KEY` in `.env`)
- A booted iOS Simulator with the target `.app` installed
- gbrain configured (`/setup-gbrain`) for source-directed planning;
  optional with `--allow-local-fallback`

## Configuration

`.env` (see [`.env.example`](.env.example)):

```
OPENAI_API_KEY=sk-...
# IOS_TEST_OPENAI_MODEL=gpt-5.4   # optional model override
```

## Development

```bash
pip install -e ".[dev]"
pytest                 # full suite — mocked PATH, no real Simulator/network
pytest tests/test_installer.py
```

Tests never touch a real Simulator, network, or gbrain — fixtures live in
`tests/fixtures/` and `tests/installer_fixtures/`.

## Project layout

```
src/
  cli.py            argparse entrypoint (ios-test command)
  agent_runner.py   the agent loop + live TUI orchestration
  ai_decider.py     OpenAI next-action decider
  flow_extractor.py gbrain-directed flow discovery
  gbrain_source.py  per-app gbrain source lifecycle
  idb_wrapper.py    idb / simctl Simulator driver
  trace.py          versioned Trace / Flow / Step schema
  codegen_detox.py  trace → Detox test
  coverage_map.py   trace → coverage.json (live map)
install.sh          sourceable lib + guarded one-command installer
web/                brew.sh-style landing page + re-runner template
docs/superpowers/   design spec + implementation plan
DESIGN.md           the one pixel surface: the live coverage map
```

## License

See repository.
