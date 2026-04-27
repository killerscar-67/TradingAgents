# Design Critique: TradingAgents Web UI

_Stage: post-Phase 9 implementation, refinement._
_Reviewed against the source under `web/src/` on 2026-04-27._
_Focus: the full app shell and the four highest-traffic screens — Market, Screening, Batch, Run Detail — plus Settings._

## Overall Impression

The UI is competent, consistent, and clearly hand-built rather than thrown together: a single dark palette is reused across screens, status badges follow one system, "inherited" chips give nice provenance between steps, and the AgentTimeline narrates progress in plain English. The biggest opportunity is **layout robustness and accessibility** — a hard `min-width: 1280px` shell, weak focus states, several sub-AA text contrasts, and tight click targets are all one cleanup pass away from being solved, and they're the things a user will hit immediately on a 13" laptop or with a screen reader.

## Usability

| Finding | Severity | Recommendation |
|---|---|---|
| `AppShell.module.css:3` sets `min-width: 1280px`. On a 1366×768 laptop with browser chrome, the app horizontally scrolls — and the RunDetail layout (sidebar 240 + timeline 220 + center flex + consultant 300) leaves only ~520 px for the actual report. | 🔴 Critical | Drop the hard min-width; let `RunDetail` collapse the consultant into a tab-toggle ("Report ↔ Consultant") below ~1100 px and the timeline into a sticky icon rail below ~900 px. |
| The sidebar's "Run full workflow" button (`Sidebar.tsx:51`) silently flips `autoAdvance: true` and hops to Market. There's no global indicator that auto-advance is active, no abort affordance, and any sidebar click cancels it (`WorkflowContext.tsx:48-53`). Users will lose track of which mode they're in. | 🔴 Critical | Show a persistent "Auto-advancing through workflow" banner at the top of the shell with a Stop button while `autoAdvance === true`. Confirm before starting if any of the upstream contexts (regime, basket) already have data that will be overwritten. |
| Single-ticker analysis (RunForm) only seems reachable by clicking into a batch card from `BatchScreen` (`BatchScreen.tsx:240`). The friendliest, most polished entry point in the app — with tooltips, "Analyze AAPL" CTA copy, and contextual error messages — is buried. | 🟡 Moderate | Either add a top-level "Analyze" screen that hosts `RunForm`, or move `RunForm` to the empty state of `MarketScreen` / `BatchScreen` so it's the first thing a new user sees. |
| MarketScreen has no forward CTA (`MarketScreen.tsx:362`). It's the default screen and the densest one (regime + indices + chart + sectors + calendar + breadth), but a manual user finishes reading it and has no nudge to the next step. | 🟡 Moderate | Once `regime` has loaded, surface a `Continue to Screening →` chip near the regime card. Mirrors the inheritance chip pattern already used in `ScreeningScreen.tsx:166`. |
| `Sidebar.tsx:11-19` uses obscure Unicode glyphs (`◈ ⊞ ⊟ ◉ ⊕ ☰ ⊙`) as nav icons. Three of seven are circle-glyph variants that read the same at 14 px. | 🟡 Moderate | Swap for an icon set already common in React apps (Lucide, Heroicons). They render at the same size, support stroke-weight, and pair semantic meaning to the label. |
| `BatchScreen.tsx:247` renders raw lowercase status strings (`queued / running / completed / error`) on the cards, while `RunDetail.tsx:15-20` translates the same statuses to `Starting… / Running / Done / Failed`. Inconsistent voice across two screens looking at the same domain. | 🟡 Moderate | Lift `STATUS_LABEL` into a shared util and use it everywhere. |
| `SettingsScreen.tsx:64-69` shows a "Saved" badge for 3 s on success, but if `updateSettings` rejects there's no error path on this screen. A failed save is silent. | 🟡 Moderate | Hold the saving toast until the promise resolves; on rejection, show a red "Couldn't save: …" inline with a retry button. |
| `BatchScreen.tsx:130` removes a ticker from local state, mutating `results` and clearing `selectedSymbols`, with no undo. Easy to clobber a 20-ticker basket by accident. | 🟢 Minor | Show a 5 s "Removed AAPL · Undo" snack at the bottom of the screen. |
| In `ScreeningScreen.tsx:344`, the empty-state copy is "Run a screen to see results, or paste your own tickers" — but this screen has no paste affordance; that lives in `BatchScreen`. | 🟢 Minor | Either remove the second clause or add a "Skip screening — paste tickers directly →" link that jumps to Batch. |
| `ConsultantChat.tsx:76` renders responses in `<pre>`. The endpoint returns `answer + observations + follow_up_questions` — naturally markdown — but `<pre>` collapses it to monospace and hides any inline emphasis. | 🟢 Minor | Render with the same Markdown component already used by `ReportTabs`, and lay out observations / follow-ups as separate sections rather than concatenated text. |

## Visual Hierarchy

- **What draws the eye first** on the default Market screen: the live "Live / Delayed" pill in the top right, then the regime card (solid 18 px label on dark fill). Both are correct — the regime is the headline of this screen.
- **Reading flow** within Market is good vertically — Regime → Indices → Chart → Sectors → Calendar → Breadth — but each section header is 13 px / uppercase / `#64748b`, which makes the section titles disappear into the page. The strongest visual element on the page is now the regime label, not the page title or the section structure. Bump section titles to 14 px and lighten only the letter-spacing, keeping the color closer to `#94a3b8` so they read as nav, not afterthoughts.
- **Page titles vs. brand mark**: H1 page titles are 22 px / 600 weight (`MarketScreen.module.css:13`), while the sidebar brand "TradingAgents" is 14 px. The brand is fine being modest, but the H1 should breathe — give it a `margin-bottom: 28px` or a 2 px accent rule under it.
- **Sector tiles fight themselves** (`MarketScreen.tsx:471-486`). The tile background is tinted by sign and intensity (`rgba(22, 163, 74, …)` or `rgba(220, 38, 38, …)`), but the percentage uses `.positive` / `.negative` text color — green text on a green tile, red text on a red tile. The most informative number on each tile is the lowest-contrast element on it. Either make the tile a quiet panel and color only the percentage, or keep the tinted tile and render the percentage in `#f8fafc`.
- **Mixed type**: the sector tile uses monospace for the ETF symbol but the system stack for the percentage in the same 80 × 80 px tile. Pick one — monospace is appropriate for the ticker, sans for the value, but flag this is intentional to anyone styling these tiles or it'll keep getting "fixed."
- **AgentTimeline never collapses** (`AgentTimeline.tsx:65`). After completion the 10-row list is purely historical, but it stays at full height and steals scroll real estate from the report. Collapse to `All 10 phases complete ✓ (expand)` once `runStatus === "completed"`.

## Consistency

| Element | Issue | Recommendation |
|---|---|---|
| Color tokens | Five neutrals are used inline as raw hex across files: `#0f1117`, `#161b27`, `#1e2433`, `#1e293b`, `#334155`. They appear *correctly* applied (background → panel → input → border step), but every component re-declares them. Drift is inevitable. | Promote to CSS variables in `index.css` (`--bg`, `--surface`, `--surface-2`, `--border`, `--border-strong`) and refactor a screen at a time. |
| Status colors | `RunDetail.module.css:49-52` and `BatchScreen.module.css:202-220` define the same four status palettes independently with subtle differences (BatchScreen uses `#172554` retry, RunDetail has no retry color). | Extract a single `.statusPill--{state}` system. |
| Spacing scale | Padding values vary between `7px 10px`, `8px 10px`, `8px 12px`, `9px 16px`, `10px 12px`, `12px 14px` for visually equivalent inputs/buttons across screens. | Adopt a 4 px grid (`4 / 8 / 12 / 16 / 20 / 24 / 32`) and pin every padding to one of those steps. |
| Border radius | Mix of `4px`, `6px`, `8px`, `12px`, `999px` without a clear pattern (e.g., status pills 10–12 px vs. 999 px chart pills). | Reduce to three: `--radius-sm: 6px` (controls), `--radius-md: 8px` (panels), `--radius-pill: 999px`. |
| Input focus | `.input:focus` shifts only the border color (`#334155` → `#3b82f6`). No outline, no shadow, no offset. With `outline: none` defaults on buttons, several controls (`.runBtn`, `.startBtn`, `.basketBtn`, `.navItem`, `.workflowBtn`, `.sendBtn`, `.chartModeBtn`, `.archiveLink`) have **no visible keyboard focus indicator at all**. | Add a global `*:focus-visible { outline: 2px solid #60a5fa; outline-offset: 2px; }` rule, then opt out per-component only where you want a custom indicator. |
| Sidebar nav grouping | Seven items in one flat list — Market, Screening, Batch Analysis, Strategy, Backtest, History, Settings — mixes a sequential workflow (the first five) with a library (History) and config (Settings). | Add two dividers and section headers: "Workflow", "Library", "Configuration". |
| Hit targets | `.removeBtn` in ScreeningScreen and BatchScreen is `padding: 0 4px` around an "x" — about 14 × 16 px. `.chartModeBtn` pill is ~24 × 27 px. WCAG 2.5.5 AA recommends 24 × 24 minimum. | Bring all icon-button hit targets to a 28 × 28 minimum; keep the visual size by using a 4 px transparent halo. |

## Accessibility

- **Color contrast (computed against `#0f1117` background)**:
  - `#94a3b8` (body secondary) ≈ **6.6:1** — passes AA.
  - `#cbd5e1` (table cells, chat bubbles) ≈ **11:1** — passes AAA.
  - `#64748b` (`liveLabel`, `regimeDate`, `breadthLabel`, `resultsCount`, `indexName`, `backBtn`) ≈ **4.4:1** at sizes ≤ 13 px — **borderline AA** (the spec floor is 4.5:1). Lift to `#7a8aa3` or larger sizes.
  - `#475569` (`.empty`, `.idle`, `.timeEstimate`, `.hint`, `.sessionHint`) ≈ **2.9:1** — **fails AA for normal text**. These are real strings (e.g., the consultant idle copy is the only text in that pane until the user types). Lift to `#94a3b8`.
  - Sector tile percentages: `#4ade80` over an effective `~#1c5028` (50% opacity green over base) ≈ **4.0:1** — borderline. As above, prefer `#f8fafc` for the percentage.
- **Keyboard navigation**: every interactive control is a `<button>` (good), but several lack a focus indicator (see above). Tab through the app from the sidebar through Market and you'll lose your place mid-page.
- **Screen reader**: the chart mode groups in `MarketScreen.tsx:408-449` correctly use `aria-label="Trading session"` / `aria-label="Chart type"` and `aria-pressed` on each button. Apply the same pattern in BatchScreen card status — currently the status pill is plain text inside the card with no ARIA role. Wrap as `<span role="status" aria-label="completed">…`.
- **Touch targets**: small `removeBtn`, the chart timeframe pills, and the calendar month-nav buttons all sit below 24 × 24 px. Fine for desktop with a mouse; cramped on a touchpad and definitely too small on a tablet.
- **`live` indicator** uses `#475569` (slate) for the off state and `#4ade80` (green) for live. The "Delayed" *label* uses `#64748b`. So when delayed, the dot looks gray and the word "Delayed" looks gray — users miss that data isn't fresh. Use amber (`#fbbf24`) for the delayed dot and label so it reads as a warning, not as quiet "off."

## What Works Well

- **Inheritance chips** (`InheritedChip` used in `ScreeningScreen.tsx:166`, `BatchScreen.tsx:170`) are a small but elegant IA pattern that makes upstream-state visible without re-rendering all of it.
- **Friendly error formatting** in `RunForm.tsx:74-87` (`formatError`) is a great example of error-message empathy — translates "ticker" / "rate limit" / "timeout" into plain English with concrete next steps. This is rare in production tools.
- **AgentTimeline phases are sentences, not labels** ("Researchers debating — bull vs. bear", "Trader — drafting a proposal"). It teaches the user the workflow while it runs.
- **Tooltip copy** in `RunForm.tsx:65-72` is concrete and actionable, especially the ticker exchange-suffix hint. Keep that voice everywhere.
- **Empty states** are present and on-brand (`ScreeningScreen.tsx:344`, `ConsultantChat.tsx:62`, `AgentTimeline.tsx:54`) — most apps skip these.
- **Status pill palette** (the four pending/running/done/error pairings) is a clean, legible system; the bug is that it's duplicated in two CSS modules, not the design itself.

## Priority Recommendations

1. **Fix layout robustness and focus states first.** Drop `min-width: 1280px`, make RunDetail's three-pane layout collapse into tabs at narrower widths, and add `:focus-visible` outline tokens globally. These are mechanical, low-risk changes that fix the highest-impact accessibility and "doesn't fit on my screen" complaints.
2. **Promote the design tokens.** Move the five neutrals, the four status palettes, the spacing scale, and the border-radius set into CSS variables in `index.css`. Touching one screen at a time, you'll catch about half of the consistency findings above as you go. This is what unlocks every later visual change being a one-line edit.
3. **Make the "Run full workflow" mode visible and reversible.** A persistent banner with a Stop button while `autoAdvance === true` — the most powerful action in the app currently has the least feedback. Pair this with a forward-CTA on Market so the manual flow has the same "next step" affordance the auto flow gets.
4. **Lift secondary text contrast and shrink the `#475569` usage.** Ship a single token swap of `#475569 → #94a3b8` for body-text uses (empty states, idle copy, hints) and you'll resolve the AA failures without touching layout.
5. **Replace the Unicode nav glyphs.** Cheapest single change with the biggest first-impression payoff — the sidebar is the first thing every user sees and currently looks improvised.
