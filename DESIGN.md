# Design System — Autonomous iOS Test Generator

Scope note: this product has exactly one pixel surface — the live semantic
coverage map (T8). This DESIGN.md is deliberately scoped to that one screen.
No global type scale, no multi-surface token system; there is no second
screen. The reference implementation is
`~/.gstack/projects/integration_testing/designs/coverage-map-preview.html`
— treat it as the visual source of truth for T8.

## Product Context
- **What this is:** an AI agent that explores an iOS app and generates its
  XCUITest suite; the coverage map is the demo's only visual surface.
- **Who it's for:** hackathon judges (gbrain), watching on a projector.
- **The memorable thing:** "the code is alive / thinking." Every design
  decision serves this. A static spreadsheet-style coverage view fails the
  brief even if technically correct.

## Aesthetic Direction
- **Direction:** Bioluminescent terminal — near-black field, Swift symbols
  ignite like neurons as the agent exercises them.
- **Decoration level:** minimal structure, expressive motion. Glow and
  ignition do the work; no borders, cards, or chrome.
- **Mood:** a living system thinking out loud, not a compliance dashboard.

## Typography
- **Everything:** monospace. Berkeley Mono if licensed, else **JetBrains
  Mono** (free, projector-legible). No prose/body font — there is no prose.
- **HUD readout:** oversized (~34px) — must read from 20 feet.
- **Node labels:** ~13px. **Ticker:** ~19px.

## Color
- **Background:** `#0A0E14` (near-black, faint blue).
- **Dormant node:** `#2A3340` (barely there).
- **Exercised node:** `#5EF6A4` (phosphor mint) + soft outer bloom.
- **Active node:** `#A8FFD0` (one step warmer) + larger bloom; the only
  node at this value at any time.
- **Uncovered/dark symbol:** `#FF6B5E` (alarm coral) — the ONLY second hue,
  used only for still-dark symbols. Never as decoration.
- **Edges:** `#1C2530` dormant; brighten to mint when traversed.
- **Dim text:** `#5A6B7A`.
- No purple, no gradients, no RAG status palette, no dark-mode variant
  (it is always dark — that is the design).

## Layout
- **Approach:** poster, full-bleed graph canvas. Not a dashboard.
- **HUD:** fixed top-left — `gbrain ▸ N/M flows · K symbols dark`.
- **Legend:** fixed top-right, small.
- **Ticker:** fixed bottom-center — current `Symbol → Symbol` being exercised.
- Nothing else on screen. Graph is the hero.

## Motion (the soul — expressive is intentional here)
- **Node ignition:** ~500ms scale-up + bloom, ease-out (`@keyframes ignite`).
- **Edge traversal:** stroke brightens to mint with drop-shadow on traverse.
- **Idle breathing:** lit/active nodes pulse opacity on a ~3s loop so the
  graph feels alive between actions.
- **Dark flicker:** uncovered nodes flicker faintly (~2.4s) — unsettled,
  "not yet reached."
- **Step cadence:** ~950ms per trace step — fast enough to feel autonomous,
  slow enough to read on a projector.

## Demo Behavior
- Driven by replaying a committed `trace.json` (design T9 / Section 4
  decision), NOT a live agent loop. The screen reads the same trace +
  gbrain flow list. Ends on `xcodebuild test GREEN`.
- A screenshot of the fully-lit end state is the mandated stage fallback.

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-05-16 | One-screen design system, bioluminescent terminal, phosphor mint accent, mono type, expressive ignition motion | /design-consultation; serves the "code is alive" memorable thing; scoped to the only pixel surface (T8) |
