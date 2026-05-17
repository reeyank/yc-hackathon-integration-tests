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

_load_dotenv() {
  [[ -f .env ]] || return 0
  set -a
  # shellcheck disable=SC1091
  source ./.env
  set +a
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

_detect_scheme() {
  [[ -n "${IOS_TEST_SCHEME:-}" ]] && { echo "$IOS_TEST_SCHEME"; return; }
  local schemes
  schemes="$(xcodebuild -list -json 2>/dev/null \
    | python3 -c 'import sys,json
d=json.load(sys.stdin)
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
    | python3 -c 'import sys,json
d=json.load(sys.stdin)
print("\n".join(x["udid"] for v in d.get("devices",{}).values() for x in v if x.get("state")=="Booted"))' \
    2>/dev/null || true)"
  local n; n="$(printf '%s\n' "$booted" | grep -c . || true)"
  if [[ "$n" -ge 1 ]]; then printf '%s\n' "$booted" | head -n1
  else
    log "No booted simulator; booting default iPhone"
    local dev
    dev="$(xcrun simctl list devices available -j 2>/dev/null \
      | python3 -c 'import sys,json
d=json.load(sys.stdin)
c=[x["udid"] for v in d.get("devices",{}).values() for x in v if "iPhone" in x.get("name","")]
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
  compgen -G '*.xcworkspace' >/dev/null 2>&1 \
    || compgen -G '*.xcodeproj' >/dev/null 2>&1 \
    || die "No .xcworkspace/.xcodeproj here. Run this from your iOS app repo root."
  local app scheme udid bundle
  app="$(pwd)"
  scheme="$(_detect_scheme)"
  udid="$(_detect_udid)"
  bundle="$(_detect_bundle "$scheme" "$udid")"
  echo "$app $udid $bundle"
}

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
  # Parameter expansion, not sed: BOOTSTRAP_CMD contains '|' and '/'.
  local content; content="$(cat "$tpl")"
  printf '%s\n' "${content//\{\{BOOTSTRAP_CMD\}\}/$BOOTSTRAP_CMD}" > ./ios-test
  chmod +x ./ios-test
}

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

if [[ "${IOS_TEST_INSTALLER_LIB:-}" != "1" ]]; then
  main "$@"
fi
