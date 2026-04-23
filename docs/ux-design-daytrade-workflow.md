# UX Design — Day-Trade Workflow

> Target user: day-trader or beginner-to-intermediate investor.
> Goal: turn TradingAgents from "analyze one ticker I already picked" into a full "what should I trade today?" workflow.
> Tone: professional plain-language, every piece of jargon translated in place.

---

## 1. The workflow, end to end

Today's flow is: pick a ticker → analyze. That skips the two most important questions a day-trader asks in the morning:
**Is today a day to trade?** and **what should I trade?**

The new workflow is a 5-stage funnel that any of the stages can also be used standalone:

```
 ┌───────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌────────────────┐
 │  1. 大盤行情   │ → │ 2. 量化選股   │ → │ 3. 批量分析  │ → │ 4. 短線策略  │ → │ 5. Backtest &  │
 │ Market over- │   │  ＋自訂選股  │   │    Batch     │   │   Trade      │   │   Walkforward  │
 │ view         │   │  Screening   │   │   analyze    │   │   plan       │   │                │
 │ "What kind   │   │ "Which names │   │ "Run the 5   │   │ "Entries,    │   │ "Would this    │
 │ of day is    │   │  pass the    │   │  agents on   │   │ stops, sizes │   │ strategy have  │
 │  today?"     │   │  filters?"   │   │ the basket"  │   │  for today"  │   │ worked before?"│
 └───────────────┘   └──────────────┘   └──────────────┘   └──────────────┘   └────────────────┘
       regime              basket             reports           trade plan         validation
       ↓                   ↓                  ↓                 ↓                  ↑
       passes entry_mode   passes tickers     passes TradeRating  passes setup     can feed back
       to screen 2+3       to screen 3        to screen 4         to screen 5      into screen 4
```

Each screen produces a well-defined artifact consumed by the next. Each can also start from scratch — a user who already knows what they want to trade can jump straight to Screen 4 and ignore 1-3.

### Navigation

Left sidebar, 7 items. A **Workflow** button at the top starts you at Screen 1 and leads you through the full funnel.

| Icon | Label | Chinese | Purpose |
|---|---|---|---|
| 📊 | Market | 大盤 | Stage 1 |
| 🔎 | Screen | 選股 | Stage 2 |
| ⚙️ | Analyze | 批量分析 | Stage 3 |
| 🎯 | Strategy | 交易策略 | Stage 4 |
| 🔁 | Backtest | 回測 | Stage 5 |
| 📂 | History | 歷史 | Past runs |
| ⚙︎ | Settings | 設定 | API keys, models, data vendors |

---

## 2. Screen 1 — 大盤行情 / Market Overview

**Purpose.** Before picking any stock, know what kind of day it is. This sets the regime (trending vs. chop) and pre-selects `entry_mode` for downstream screens.

**Layout sketch**

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Today · 2026-04-23 · Markets open 3h 12m        Live · streaming ●      │
├──────────────────────────────────────────────────────────────────────────┤
│  ┌─ Indices ──────────────────────────────────────────────────────────┐  │
│  │  S&P 500  5,812  +0.4%   NASDAQ  18,234  +0.7%   VIX  14.2  -3.1% │  │
│  │  HSI      19,455 -0.2%   Nikkei  38,122  +0.1%   TSX   24,810 +0.3│  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌─ Regime ──────────────────────────┐  ┌─ Breadth ──────────────────┐  │
│  │  Trending bull — 72% confidence   │  │ 68% of stocks above 50-day │  │
│  │  ADX 28, VIX low, breadth strong  │  │ 124 new highs, 22 new lows │  │
│  │  Today favors: Breakout setups    │  │ Adv/Dec  3.2 : 1           │  │
│  │  [Use in Screening →]             │  │                            │  │
│  └────────────────────────────────────┘  └────────────────────────────┘  │
│                                                                          │
│  ┌─ Sector heatmap ──────────────────────────────────────────────────┐  │
│  │  Tech +1.2%   Energy +0.8%   Finance +0.4%   Staples -0.2%  ...  │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌─ Economic calendar (today) ───────────────────────────────────────┐  │
│  │  08:30  US Initial Jobless Claims  (medium impact)                │  │
│  │  14:00  FOMC Minutes               (high impact — expect volatility)│
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│                                    [Continue to screening →]             │
└──────────────────────────────────────────────────────────────────────────┘
```

**Key copy**

- **Regime tooltip:** "We look at trend strength (ADX), volatility (VIX/ATR), and breadth to classify today as trending, choppy, or risk-off. The entry mode below is set to match."
- **Breadth tooltip:** "How widely the rally is participated. 'Narrow' rallies (led by a few names) are weaker signals than 'broad' ones."
- **High-impact event warning:** "FOMC Minutes release at 14:00. Expect spikes in volatility around that time — consider avoiding new entries 15 minutes before."
- **Empty state (markets closed / weekend):** "Markets are closed. Showing last session — Friday, Apr 17. Run analysis 'as of' a past date to backtest instead."
- **Live feed indicator:** Small green dot + "Live · streaming" when the WebSocket is connected; "Reconnecting…" on drop; "Delayed 15 min" if fallback to a delayed quote feed kicks in.

### 2.1 Benchmarks used

Since the user trades cross-border (US + HK + JP via Futu), the screen surfaces benchmarks in three layers. A **Home market** setting in Settings (default: US) determines which benchmarks get the big tiles and drives the default regime; the other regions show as a compact rotator.

**Layer 1 — Home-market tiles (prominent).** One row per home market.

| Home market | Broad index | Tech / growth | Second-tier | Volatility |
|---|---|---|---|---|
| US | S&P 500 `^GSPC` | NASDAQ 100 `^NDX` | Russell 2000 `^RUT` | VIX `^VIX` |
| HK | Hang Seng `^HSI` | HS Tech `^HSTECH` | HSCEI `^HSCE` | VHSI `^VHSI` |
| JP | Nikkei 225 `^N225` | TOPIX `^TOPX` | TSE Growth | — (no mainstream vol index) |
| TW | TAIEX `^TWII` | TPEx (OTC) | — | — |
| CN | CSI 300 `000300.SS` | STAR 50 `000688.SS` | Shanghai Comp `^SSEC` | — |
| CA | TSX Composite `^GSPTSE` | — | TSX Venture `^SPCDNX` | — |
| UK / EU | FTSE 100 `^FTSE` | STOXX 600 `^STOXX` | DAX `^GDAXI` | VSTOXX |

**Layer 2 — Region rotator.** Small tiles for the non-home regions so a HK-home user still sees what the US did overnight (and vice versa).

**Layer 3 — Cross-asset strip (collapsible, under indices).** These aren't regime inputs but they set context — users can expand them when they want to understand *why* today's regime changed.

| Asset | Symbol | What it tells you |
|---|---|---|
| US 10-year yield | `^TNX` | Rising = pressure on growth stocks, strengthens USD |
| 2s10s spread | `^TNX − ^FVX` | Inversion = classic recession signal |
| DXY (dollar index) | `DX-Y.NYB` | Strong USD pressures EM and commodities |
| Gold | `GC=F` | Risk-off flows, inflation hedge |
| Oil (WTI) | `CL=F` | Energy, inflation proxy |
| Bitcoin | `BTC-USD` | Risk appetite / liquidity gauge |
| HYG / IEF ratio | `HYG` ÷ `IEF` | Credit risk appetite. Falling = stress |

### 2.2 Regime classification — inputs

The "Trending bull / Choppy / Risk-off" label is a deterministic rule-based classifier over per-home-market inputs (no LLM — needs to be reproducible for the backtest):

| Input | Source | Threshold / interpretation |
|---|---|---|
| ADX(14) on home index daily | `^GSPC` / `^HSI` / `^N225` etc. | ≥25 = trending · 20–25 = weakening · <20 = range-bound |
| Price vs 50-day SMA | Home index | Above = bull · below = bear |
| Price vs 200-day SMA | Home index | Above = secular bull · below = secular bear |
| VIX level | `^VIX` (or `^VHSI` for HK) | <15 complacent · 15–20 normal · 20–30 elevated · >30 risk-off |
| VIX slope (20-day) | `^VIX` | Rising = caution · falling from high = relief |
| % of index above 50-day MA | Derived from constituents | >60% broad · 40–60% mixed · <40% narrow |
| 20-day new highs − new lows | Derived from constituents | Positive widening = broad strength · negative = distribution |
| HYG / IEF 20-day change | `HYG` ÷ `IEF` | Falling ≥2% in 20 days → risk-off tag regardless of equity action |

**Output tags** (one primary, plus secondary if warranted):
`Trending bull` · `Trending bear` · `Choppy / range-bound` · `Risk-off` · `Squeeze / pre-breakout`

Each carries a confidence score (0–100) computed as a weighted vote across the inputs above. The regime → `entry_mode` mapping:

| Regime | Default entry mode |
|---|---|
| Trending bull / bear | `breakout` |
| Choppy / range-bound | `mean_reversion` |
| Risk-off | `auto` with a "reduce size" flag |
| Squeeze | `breakout` (volatility expansion expected) |

### 2.3 Regime per universe (mixed-basket behavior)

Regime is computed per benchmark. When the user later builds a mixed basket in Screen 2, each ticker inherits its primary exchange's regime:

- US ticker → S&P 500 regime.
- HK ticker → HSI regime.
- JP ticker → Nikkei regime.
- Mixed basket → per-ticker regime chips shown in the screening results, each with its own suggested entry mode.

This is why Screen 2's "Regime today: Trending" chip in the header needs to become "Regime: varies (3 US / 2 HK)" when the basket spans multiple markets.

### 2.4 Breadth indicators (shown in the Breadth card)

Computed per home market, refreshed every ~5 minutes during market hours:

| Indicator | Formula |
|---|---|
| % above 50-day MA | Index constituents with `close > SMA(50)` ÷ total constituents |
| % above 200-day MA | Same as above, 200-day window — secular breadth |
| New highs vs new lows | Count of 52-week highs − count of 52-week lows on the day |
| Advance/decline ratio | Advancers ÷ decliners |
| McClellan Oscillator | 19-day EMA of (advances − declines) − 39-day EMA of same |

For HK, compute against HSI constituents. For JP, against Nikkei 225 constituents. For Futu-sourced data these come straight from the constituent universe.

### 2.5 Sector heatmap — proxies per region

| Home market | Sector proxy set |
|---|---|
| US | 11 GICS sector ETFs: `XLK XLE XLF XLV XLP XLY XLI XLU XLB XLC XLRE` |
| HK | Hang Seng sub-indices: `HSCI` financials, IT, utilities, consumer, energy, properties, industrials, healthcare |
| JP | TOPIX-17 sector indices |
| TW | TAIEX industry sub-indices (electronics, financials, etc.) |
| Others | Fall back to the broad index only |

Each cell shows today's %; hover/tap reveals 1d, 5d, 1m. The color ramp uses a diverging scale (red → neutral → green), not a linear one, so small moves stay visually muted.

### 2.6 Economic calendar source

Pull from a single aggregator endpoint (FMP, TradingEconomics, or ForexFactory — pick one in Settings). Filter to:

- User's home market country plus any region whose tickers are in today's basket.
- **Medium** and **high** impact only (low impact adds noise).
- Today and next trading day.

High-impact events to surface explicitly (`event_risk_flag: true`):

| Region | Events |
|---|---|
| US | FOMC decision / minutes · NFP · CPI · PPI · GDP · retail sales · ISM PMI · jobless claims (weekly) |
| HK / CN | PBoC rate · loan prime rate · China CPI / PPI · China GDP · manufacturing PMI |
| JP | BoJ rate · Tankan · Japan CPI |

**Data flow out:** `regime`, `suggested_entry_mode`, `event_risk_flag`, `home_market`, per-region regime map → used as defaults in Screen 2.

---

## 3. Screen 2 — 量化選股＋自訂選股 / Stock Screening

**Purpose.** Produce a basket of 3–20 tickers to run full analysis on.

**Layout sketch**

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Screening                                        Regime today: Trending │
├──────────────────────────────────────────────────────────────────────────┤
│  ┌─ Quant screen ────────────────────────┐  ┌─ Custom list ──────────┐  │
│  │ Universe: [ S&P 500        ▼ ]        │  │ Add ticker             │  │
│  │ Strategy: (•) Breakout  ( ) Mean rev  │  │ ┌──────────────────┐   │  │
│  │           ( ) Auto (from regime)      │  │ │ AAPL             │+  │  │
│  │                                       │  │ └──────────────────┘   │  │
│  │ Filters:  [✓] Momentum                │  │ Or: Paste / CSV import │  │
│  │           [✓] Squeeze                 │  │                        │  │
│  │           [ ] S/R proximity           │  │ My watchlist (★):       │  │
│  │           [✓] Volume surge            │  │  NVDA   ☆ SHOP.TO      │  │
│  │                                       │  │  9984.T                 │  │
│  │ Score: top N = [ 20 ]  min = [ 0.65 ] │  │                        │  │
│  │                                       │  │                        │  │
│  │ [Run screen]                          │  │                        │  │
│  │                                       │  │                        │  │
│  │ Results (18 matches):                 │  └────────────────────────┘  │
│  │ ☐ NVDA   0.89  Breakout setup   +2.1% │                              │
│  │ ☐ AVGO   0.84  Momentum + vol   +1.8% │  ┌─ Basket ──────────────┐  │
│  │ ☐ META   0.82  Coil forming     +0.9% │  │ 5 tickers selected    │  │
│  │ ...                                   │  │  NVDA · META · AAPL · │  │
│  │ [Select all]                          │  │  SHOP.TO · 9984.T     │  │
│  └───────────────────────────────────────┘  │                        │  │
│                                              │ Est. cost: ~$0.48      │  │
│                                              │ Est. time: 9–12 min    │  │
│                                              │                        │  │
│                                              │ [Analyze 5 tickers →] │  │
│                                              └────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
```

**Key copy**

- **Universe selector placeholder:** "Pick a universe or paste your own list."
- **Strategy helper text (under radio):** "Breakout scores names about to break above resistance. Mean-reversion scores names pulling back to support."
- **Filter tooltips:**
  - Momentum: "Price and volume are accelerating in one direction."
  - Squeeze: "Volatility has contracted — often precedes a big move."
  - S/R proximity: "Price is close to a known support or resistance level."
  - Volume surge: "Today's volume is well above the 20-day average."
- **Empty results:** "No tickers passed today's filters. Try loosening the minimum score or picking a different universe."
- **Score tooltip:** "Composite of the enabled filters. 1.0 = all filters pass strongly. Above 0.65 is typical."
- **Cost/time estimate:** "Based on your current models. Switch to a cheaper 'quick-think' model in Settings to run more tickers per run."
- **Basket over limit warning:** "20+ tickers will take 30+ minutes. Consider splitting into two runs."

**CTA (primary):** `Analyze N tickers →`
**CTA (secondary):** `Save basket as watchlist` · `Clear basket`

**Data flow in:** `suggested_entry_mode` from Screen 1.
**Data flow out:** `ticker_basket` → Screen 3.

---

## 4. Screen 3 — 批量分析 / Batch Analysis

**Purpose.** Run the full TradingAgents pipeline on every ticker in the basket. This is the existing single-ticker analysis fanned out.

**Layout sketch**

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Batch analysis · 5 tickers · 3 done · ETA 4m                 [Stop all] │
├──────────────────────────────────────────────────────────────────────────┤
│  ┌─ NVDA ──────────┐ ┌─ META ──────────┐ ┌─ AAPL ──────────┐            │
│  │ ✓ Done          │ │ ✓ Done          │ │ ◐ Risk review   │            │
│  │ ▲ BUY           │ │ = HOLD          │ │ 3:12 elapsed    │            │
│  │ Entry 142.30    │ │ "Mixed signal — │ │                 │            │
│  │ Stop  138.50    │ │  wait"          │ │ [View partial]  │            │
│  │ [View report]   │ │ [View report]   │ │                 │            │
│  └─────────────────┘ └─────────────────┘ └─────────────────┘            │
│  ┌─ SHOP.TO ───────┐ ┌─ 9984.T ────────┐                                │
│  │ ◐ Researchers…  │ │ ⏳ Queued       │                                │
│  │ 1:45 elapsed    │ │ Next up         │                                │
│  └─────────────────┘ └─────────────────┘                                │
│                                                                          │
│  Live feed:                                                              │
│  16:02:18  AAPL  Risk team reviewing aggressive scenario                 │
│  16:02:05  SHOP.TO  Bull researcher, round 1                             │
│  16:01:44  META  Portfolio manager finalized: HOLD                       │
│                                                                          │
│                                  [View strategy (3 of 5 ready) →]        │
└──────────────────────────────────────────────────────────────────────────┘
```

**Key copy**

- **Running tile state (per ticker):** "NVDA — Trader drafting a proposal"
- **Partial failure:** "META: Fundamentals analyst timed out. Retry this one, or continue without it?" → [Retry] [Skip]
- **Full failure:** "Couldn't finish NVDA after 3 tries. Check Settings → Providers, or skip this ticker to keep going."
- **Cost-cap hit:** "You've used ~80% of the estimated cost for this run. Keep going or stop and review?"
- **All done banner:** "Finished. 4 of 5 tickers have ratings. See strategy →"
- **Stop confirmation:** "Stop all 5 analyses? In-progress work won't be saved." → [Stop all] [Keep running]

**Data flow in:** basket from Screen 2.
**Data flow out:** map of `ticker → TradeRating + TradeSetup` → Screen 4.

---

## 5. Screen 4 — 短線交易策略 / Short-Term Trading Strategy

**Purpose.** Turn the pile of individual analyses into a concrete trade plan for today: entries, stops, targets, position sizes.

**Layout sketch**

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Today's trade plan · 2026-04-23                                         │
│  Mode: Breakout (from today's regime)  Horizon: (•) Intraday ( ) Swing   │
├──────────────────────────────────────────────────────────────────────────┤
│  Portfolio size: $100,000   Risk per trade: 1% ($1,000)  (per-strategy)  │
│                                                                          │
│  ┌─ Trades (click a row to see the chart) ──────────────────────────┐   │
│  │ Ticker  Rating  Entry    Stop     Target  Size    R:R   Notes    │   │
│  │▶NVDA    ▲ BUY   142.30  138.50   152.00   263 sh  2.4  "Break of │   │
│  │                                                         resist."  │   │
│  │ AAPL    ▲ BUY   178.50  175.20   185.00   303 sh  2.0           │   │
│  │ SHOP.TO ▲ BUY    98.40   95.80   104.00   385 sh  2.2           │   │
│  │ META    = HOLD   —       —        —        —       —   Skipped   │   │
│  │ 9984.T  ▼ SHORT  3,820   3,920    3,620    -26 sh  2.0  "Break of │   │
│  │                                                         support." │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  ┌─ NVDA · 1D · candles + volume ───────────────────────────────────┐   │
│  │                                  ╭─────── Target 152.00 ─────────┤   │
│  │                         ╭──╮ ╭╮ ╭╯                                │   │
│  │                      ╭──╯  ╰─╯╰─╯                  ← Entry 142.30│   │
│  │                  ╭─╮ ╯                                            │   │
│  │       ╭──╮     ╭─╯ ╰╯                       ← Stop  138.50       │   │
│  │ ╭─╮╭──╯  ╰─────╯                                                  │   │
│  │ ╯ ╰╯                                                              │   │
│  │ ▁▂▁▃▄▂▃▅▆▄▅▇▆█▅▄▆▇▆█▅▃ volume                                   │   │
│  │ 1m  5m  15m  1h  4h [1D]  1W             + SMA 20 · ADX · Vol   │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  ┌─ Exposure ─────────────────────┐  ┌─ Risk ──────────────────────┐    │
│  │ Gross    $181,570 (182%)       │  │ Max loss if all stops hit:  │    │
│  │ Net long $82,300  (82%)        │  │ -$3,950 (3.95% of equity)   │    │
│  │ Short    $99,270  (99%)        │  │ Worst-case (gaps × 2):      │    │
│  │ By sector: Tech 64%, Retail 18%│  │ -$7,900 (7.9%)              │    │
│  └────────────────────────────────┘  └──────────────────────────────┘    │
│                                                                          │
│  [Copy to clipboard] [Export CSV] [Send to Futu] [Save as preset]        │
│                                           [Backtest this strategy →]     │
└──────────────────────────────────────────────────────────────────────────┘
```

**Key copy**

- **Mode explainer:** "Breakout: buy as price breaks above resistance. Mean reversion: buy as price bounces from support. Mixed: mix of both, depending on each ticker."
- **Horizon explainer:** "Intraday: close every position by market close. Swing: hold overnight for 1–5 days."
- **Risk per trade tooltip:** "Stop-loss distance × position size = this dollar amount. Most day-traders keep this at 0.5–1% of total equity per trade."
- **Skipped trade row:** "META — HOLD. The agents couldn't agree on a direction; no trade."
- **Short position tooltip:** "Short signals sell the stock first and buy it back later. Profits if the price falls. Requires a margin-enabled account — make sure your Futu account has shorting permissions for this ticker."
- **Short stop tooltip (above entry):** "For shorts, the stop sits above your entry — the price you buy back at if the trade goes against you."
- **Gross/Net exposure tooltip:** "Gross = total dollars at work (longs + shorts). Net = longs minus shorts. If gross > 100%, you're using margin. High gross with low net means you're market-neutral."
- **Max-loss banner:** "If every stop gets hit today, you lose $3,950 (3.95%). Acceptable? Adjust risk-per-trade to change."
- **Concentration warning:** "64% of today's exposure is in Tech. Consider trimming or hedging if that's more than your usual concentration limit."
- **Portfolio size tooltip:** "Saved with this strategy preset, not globally. Different strategies can use different account sizes — useful for testing a strategy on a paper-sized portfolio before scaling."
- **Send to Futu button states:**
  - Default: `Send to Futu` → opens confirmation dialog.
  - Confirmation dialog: "Stage 4 orders in your Futu account? These are staged, not placed — you'll still need to review and submit inside Futu."
  - Success: "Staged in Futu. Open the Futu app to review and submit."
  - Auth needed: "Connect your Futu account in Settings → Broker to enable this."
  - Market closed: "Futu accepts staged orders when markets reopen in 3h 12m. Stage now?"

**CTA (primary):** `Backtest this strategy →`
**CTA (secondary):** `Copy to clipboard` · `Export CSV` · `Send to Futu` · `Save as preset`

**Broker integration (Futu).** v1 integrates with Futu / moomoo via the OpenD gateway. The integration stages orders in the user's Futu account but does not submit them — the user must still hit submit inside Futu. This keeps us inside "no autonomous trade execution" even though the export is now one click instead of a CSV round-trip.

**Data flow in:** ratings + setups from Screen 3, regime from Screen 1.
**Data flow out:** `strategy_config` snapshot → Screen 5.

---

## 6. Screen 5 — Backtest & Walkforward

**Purpose.** Validate the deterministic trade plan artifact produced by this workflow against historical bars. The workflow still matters because regime, basket selection, ratings, and risk settings decide what gets frozen into the trade plan, but the historical replay itself is quant-strict and reproducible. Walk-forward specifically prevents the "it looks great because we tuned it on the same data" trap.

**Important mode note.** Backtest and walk-forward run in `quant_strict` mode — the deterministic quant signal drives the trade rating and no LLM runs inside the replay loop. The backtest artifact is therefore: `workflow inputs frozen at run time` + `deterministic quant-strict historical execution`. That is the only way to make multi-year simulations tractable and reproducible.

**Layout sketch**

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Backtest & walkforward                                                  │
├──────────────────────────────────────────────────────────────────────────┤
│  ┌─ Mode ────────────────────────────────────────────────────────────┐  │
│  │ ⚡ Deterministic backtest — quant signal only, no LLM.            │  │
│  │    Runs in minutes, same result every time.    [What's this?]     │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌─ Config ──────────────────────────────────────────────────────────┐  │
│  │ Strategy:   Today's trade plan (loaded)              [Edit]        │  │
│  │ Period:     From [2024-01-01] To [2026-04-23]                      │  │
│  │             [Last 30d] [Last 90d] [YTD] [Last year] [Max]          │  │
│  │ Rebalance:  (•) Daily  ( ) Weekly                                  │  │
│  │                                                                    │  │
│  │ Walk-forward:                                                      │  │
│  │   In-sample window:   [ 60 ] trading days                          │  │
│  │   Out-of-sample:      [ 20 ] trading days                          │  │
│  │   Step forward by:    [  5 ] trading days                          │  │
│  │                                                                    │  │
│  │ Est. runtime: ~2 min · Est. cost: $0 (no LLM calls)                │  │
│  │                                           [Run backtest]           │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌─ Equity curve ───────────────────────────────────────────────────┐   │
│  │   (line chart — in-sample vs. out-of-sample in different shades) │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  ┌─ KPIs (out-of-sample only) ──────────────────────────────────────┐   │
│  │ Total return +18.4%   CAGR +7.9%   Sharpe 1.24   Sortino 1.61    │   │
│  │ Max drawdown -11.8%   Win rate 54%   Profit factor 1.45          │   │
│  │ Trades 214   Avg hold 1.8 days   Best day +4.1%  Worst -3.3%     │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  ┌─ Sensitivity ────────────────────────────────────────────────────┐   │
│  │ How results change as you tweak:                                  │   │
│  │   • Min score:  0.55 → 0.65 → 0.75  (Sharpe 0.9 / 1.2 / 1.3)      │   │
│  │   • Stop width: 1% → 2% → 3%        (Sharpe 1.5 / 1.2 / 0.9)      │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  ┌─ Trade log (click a trade to replay) ─────────────────────────────┐  │
│  │ Date         Ticker   Side   Entry   Exit    P&L      Bars held   │  │
│  │▶2025-03-14   NVDA     LONG   118.40  122.80  +3.7%    4           │  │
│  │ 2025-03-14   META     LONG   612.00  608.50  -0.6%    1 (stopped) │  │
│  │ 2025-03-17   SHOP.TO  LONG    85.20   91.60  +7.5%    6           │  │
│  │ ...                                                                │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌─ Trade replay — NVDA 2025-03-14 ──────────────────────────────────┐  │
│  │                                                                    │  │
│  │                                 ▲ exit 122.80 (+3.7%)              │  │
│  │                          ╭╮╭╮╭──╯                                  │  │
│  │                       ╭──╯╰╯╰╯                                     │  │
│  │                    ╭──╯                                            │  │
│  │             ╭╮   ╭─╯ ● entry 118.40                                │  │
│  │    ╭╮╭──╮ ╭╯╰╮╭─╯                                                  │  │
│  │ ╭──╯╰╯  ╰─╯  ╰╯                   ...stop 115.20 (not hit)         │  │
│  │                                                                    │  │
│  │ [‹ prev trade]  [▶ play bar-by-bar]  [next trade ›]               │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  [Save run as "Breakout v2 — Apr 2026"]  [Compare to...]  [Export]       │
└──────────────────────────────────────────────────────────────────────────┘
```

**Key copy**

- **Walk-forward explainer (hero block, collapsible):**
  > "Walk-forward splits history into overlapping chunks. For each chunk, we use the first N days (in-sample) to calibrate, then trade the next M days (out-of-sample) without peeking. That's closer to real life — you never get to tune a strategy on the same data you're trading."
- **In-sample / out-of-sample tooltip:**
  - In-sample: "The training window. We let the strategy see this data to pick parameters."
  - Out-of-sample: "The test window. The strategy has to trade this blind."
- **Step forward tooltip:** "How far we slide the window each time. Smaller = more overlap, slower to run. Larger = fewer chunks, faster but noisier."
- **Sharpe tooltip:** "Risk-adjusted return. Above 1.0 is decent, above 2.0 is excellent — but be skeptical of backtests that show very high Sharpe."
- **Drawdown tooltip:** "Worst peak-to-trough loss during the test. -11.8% means at one point the strategy was down 11.8% from its highest prior value."
- **Overfitting warning (auto-triggered when in-sample >> out-of-sample):**
  > "The strategy did much better in-sample (Sharpe 2.1) than out-of-sample (Sharpe 0.6). That's a classic sign of overfitting — the parameters may be fit to noise, not signal. Try widening the in-sample window or simplifying the filters."
- **Small-sample warning:** "Only 12 trades over this window. That's too few to draw conclusions. Expand the date range."
- **Past-performance disclaimer (footer, always visible):** "Backtests assume perfect execution and don't include slippage, gaps, or halts. Live results will be worse."
- **Mode banner "What's this?" popover:** "Backtests run in quant-strict mode: the deterministic signal decides every trade, the LLM never runs. Live trading with the full 5-agent pipeline may diverge from these results — the backtest is a floor on how well the quant signal alone performs, not a prediction of live LLM-assisted runs."

**Data flow in:** `strategy_config` from Screen 4 (or loaded from a saved preset).
**Data flow out:** `backtest_run` artifact, saved to History.

---

## 7. Screen 6 — 歷史 / History

**Purpose.** Provide one place to reopen any saved workflow artifact or legacy archive without the user needing to remember whether it came from the old single-ticker UI or the new day-trade workflow.

**What appears here**

History is a unified feed. It must include all of the following item types:

- Legacy single-ticker archived analyses already stored on disk under `results_dir`
- Batch analysis runs from Screen 3
- Saved trade-plan / strategy artifacts from Screen 4
- Backtest runs from Screen 5
- Broker stage requests created by `Send to Futu`

Every item in the feed must expose at least:

- stable id
- item type
- created / completed timestamps
- ticker or basket summary
- home market
- workflow session id, if present
- status
- primary path reference into `results_dir`, if applicable
- summary metadata needed for the list view without opening the full report

**Layout sketch**

```
┌──────────────────────────────────────────────────────────────────────────┐
│  History / Past runs                                                     │
├──────────────────────────────────────────────────────────────────────────┤
│ Filters: [All types ▼] [All markets ▼] [Status ▼] [Date range ▼]       │
│ Search:  [ ticker / basket / preset / run id                      ]     │
│                                                                          │
│ 2026-04-23                                                               │
│ ┌─ Batch analysis ─ 5 tickers · completed · workflow sess-1024 ──────┐ │
│ │ NVDA · AAPL · SHOP.TO · 9984.T · META        [Open strategy] [Re-run]│ │
│ └──────────────────────────────────────────────────────────────────────┘ │
│ ┌─ Strategy plan ─ Breakout v2 · US home market ─────────────────────┐ │
│ │ 4 trades · gross 182% · max loss 3.95%      [Open] [Backtest again] │ │
│ └──────────────────────────────────────────────────────────────────────┘ │
│ ┌─ Backtest ─ OOS Sharpe 1.24 · Max DD -11.8% ───────────────────────┐ │
│ │ 2024-01-01 → 2026-04-23                           [Open] [Compare]   │ │
│ └──────────────────────────────────────────────────────────────────────┘ │
│ ┌─ Legacy analysis ─ MSFT · single ticker archive ───────────────────┐ │
│ │ Completed in old UI flow                              [Open report]  │ │
│ └──────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
```

**Filters and actions contract**

- Filter by item type: `legacy_analysis`, `batch_analysis`, `strategy_plan`, `backtest_run`, `broker_stage_request`
- Filter by market, status, and date range
- Search by ticker, basket name, preset name, workflow session id, or run id
- Primary action opens the artifact in its native screen
- Secondary actions are item-type specific:
  - batch analysis: `Open strategy`, `Re-run`
  - strategy plan: `Open`, `Backtest again`, `Duplicate as preset`
  - backtest run: `Open`, `Compare`, `Export`
  - broker stage request: `View staged orders`, `Duplicate`
  - legacy analysis: `Open report`, `Create strategy from archive` when enough context exists

**Archive compatibility rule**

Legacy disk-only archives must show up in History even if they have no SQLite row yet. On first open or list scan, the backend may hydrate a metadata row into SQLite, but the user experience must treat old and new artifacts as one continuous history.

---

## 8. Screen 7 — 設定 / Settings

**Purpose.** Central place for all persistence-heavy defaults that influence workflow sessions, estimates, providers, and broker staging.

**Sections**

- General
  - Home market
  - Default workflow shortcut universe per market
  - Output language
- Models & Providers
  - LLM provider
  - deep-think model
  - quick-think model
  - data vendors
  - live quote mode and delayed fallback behavior
- Workflow Defaults
  - default top-N screen size
  - default score floor
  - default risk-per-trade
  - default portfolio size
  - allow shorts by default
- Broker
  - Futu / OpenD connection settings
  - stage-only enabled indicator
- Watchlists & Presets
  - saved watchlists
  - strategy presets

**Layout sketch**

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Settings                                                               │
├──────────────────────────────────────────────────────────────────────────┤
│ General         Models & Providers        Workflow Defaults   Broker     │
│                                                                          │
│ Home market:            [ US ▼ ]                                        │
│ Default shortcut list:  [ S&P 500 ▼ ]                                   │
│ Output language:        [ English ▼ ]                                   │
│                                                                          │
│ LLM provider:           [ openai ▼ ]                                    │
│ Deep-think model:       [ gpt-5.4 ▼ ]                                   │
│ Quick-think model:      [ gpt-5.4-mini ▼ ]                              │
│                                                                          │
│ Risk per trade:         [ 1.0 % ]                                       │
│ Portfolio size:         [ 100000 ]                                      │
│ Allow shorts by default [✓]                                             │
│                                                                          │
│ Futu / OpenD:           Connected ●                                     │
│ [Save settings]                                         [Test broker]   │
└──────────────────────────────────────────────────────────────────────────┘
```

**Persistence contract**

- Settings are global defaults persisted in SQLite.
- A workflow session snapshots the settings values it inherited at creation time so later changes do not silently mutate an in-progress session.
- Saved strategy presets can override the global defaults for `portfolio_size`, `risk_per_trade`, and `allow_shorts`.

---

## 9. Cross-cutting design notes

---

### 9.1 State that flows between screens

```
Screen 1 ──regime, entry_mode, event_risk─────▶ Screen 2
Screen 2 ──ticker_basket──────────────────────▶ Screen 3
Screen 3 ──{ticker → rating + setup}──────────▶ Screen 4
Screen 4 ──strategy_config (mode, risk, plan)─▶ Screen 5
Screen 5 ──backtest_run, optional tweaks──────▶ History
         ◀──(re-apply adjusted params)────────  Screen 4
```

### 9.1a Workflow session lifecycle

Every top-level journey is represented by a `workflow_session` row in SQLite.

Session states:

- `draft`: screen opened, no durable artifact yet
- `active`: at least one durable artifact created
- `completed`: user reached a terminal artifact they chose to save
- `archived`: hidden from default active-session lists but still present in History

Minimum session fields:

- `session_id`
- `current_screen`
- `home_market`
- inherited upstream references (`market_overview_id`, `screening_run_id`, `basket_id`, `batch_id`, `strategy_id`, `backtest_id`)
- snapshot of effective settings defaults at session start
- created / updated timestamps

Resume behavior:

- Opening an unfinished session restores the user to `current_screen` with the latest saved upstream artifacts.
- Completing a later screen does not delete earlier artifacts; it links them into the same session timeline.
- History can group by workflow session or flatten by artifact type.

Each screen should show a compact "inherited from" chip near the top so the user can see what came from upstream:
- Screen 2: `Regime: Trending (from Market)` with a link back.
- Screen 3: `5 tickers (from Screening)`.
- Screen 4: `Setups: 3 BUY, 1 HOLD, 1 SELL (from Batch analysis)`.
- Screen 5: `Strategy: Today's plan (from Trade plan)`.

### 9.2 Starting from any screen

Every screen accepts a "blank start":
- Screen 2 without a Screen 1 regime → defaults to `entry_mode: auto`.
- Screen 3 without a Screen 2 basket → shows a "paste or pick tickers" inline mini-screener.
- Screen 4 without a Screen 3 run → empty state with "Run a batch analysis first, or add trades manually" and a way to manually enter setups.
- Screen 5 without a Screen 4 strategy → shows saved presets to choose from, or "Build a strategy first."

### 9.3 "Do it all at once" shortcut

Power-user shortcut on the home screen: **Run full workflow** button. Behaves like:
1. Pull market data → classify regime.
2. Run quant screen with defaults for the selected `home_market` (top 10 from the default home-market universe: `S&P 500` for US, `HSI` for HK, `Nikkei 225` for JP, etc.).
3. Batch-analyze the 10.
4. Assemble a trade plan.
5. Show Screen 4 when done.

One click, ~10 minutes, clear status along the way.

### 9.4 Shared copy patterns (reuse of earlier UX work)

All errors follow: **what happened · why · how to fix**.
All CTAs are verb-first outcomes, not "Submit" or "OK".
All jargon gets a tooltip, and the tooltip explains in plain language before showing the technical term.
Every long-running action shows an estimated time and cost before the user commits.

### 9.5 Language

Primary labels in the user's `output_language`. Parenthetical English terms kept for ambiguous finance terms (`走勢回歸 (Mean reversion)`). Code-level strings (ticker suffixes, parameter names like `entry_mode`) are never localized.

### 9.6 Charting

**v1 library: TradingView `lightweight-charts` (MIT).** One shared chart component used across Screens 1, 2, 4, and 5. Chosen for v1 because it ships today with no approval step, which matters while the Advanced Charts license application is in review.

**v2 upgrade path: TradingView Advanced Charts (Charting Library).** Migrate once the license is approved. The same Datafeed layer feeds both, so the migration is a component swap, not a data rewrite.

**Per-screen chart usage**

| Screen | Chart surface | Library in v1 |
|---|---|---|
| 1 · Market | Home-index chart with ADX, 50 SMA, 200 SMA overlays. Medium embed (~400px tall). | lightweight-charts |
| 2 · Screening | Inline sparkline per result row (60×20 px, last 20 days, colored by direction). | lightweight-charts (minimal) |
| 4 · Trade plan | Full candle + volume chart for the selected trade row, with entry / stop / target price lines. Timeframe selector (1m / 5m / 15m / 1h / 4h / 1D / 1W). | lightweight-charts |
| 5 · Backtest, equity curve | Line chart, in-sample vs. out-of-sample shaded separately. | lightweight-charts |
| 5 · Backtest, trade replay | Candle chart with entry / exit markers, optional bar-by-bar playback. | lightweight-charts |

**Indicator set (v1).** Only indicators the quant engine actually uses, so the chart and the algorithm stay in sync:

- Moving averages: SMA(20), SMA(50), SMA(200), EMA(20).
- ADX(14) — trend strength (shown as subchart).
- Bollinger Bands + Keltner Channels — for the squeeze filter.
- VWAP — intraday reference level.
- Volume — always shown as histogram subchart.

No RSI, MACD, Ichimoku, etc. in v1 — we add them when the engine actually references them. Keeps the chart honest about what the algorithm considered.

**Price lines for trade plans (Screen 4).** Three persistent horizontal lines per trade: entry (neutral), stop (red, below for longs / above for shorts), target (green). Labels render at the right edge with the price value. Uses `createPriceLine()` in lightweight-charts; migrates to `createShape({shape: 'horizontal_line'})` in the Advanced Charts port.

**Trade replay markers (Screen 5).** Buy/sell markers on the time axis at the trade's entry and exit bars. Uses `setMarkers()` in lightweight-charts.

**Timeframe selector.** Seven buttons: 1m, 5m, 15m, 1h, 4h, 1D, 1W. Default per surface: 1D for Screens 1, 2, and 5; 5m or 15m for Screen 4 depending on `horizon` (Intraday → 5m, Swing → 1D).

**Data consistency requirement.** This is the one hard rule regardless of library: chart bars must come from the same vendor and normalization as the quant engine used for the analysis. If Screen 4 shows a trade computed on Futu bars, the chart must render Futu bars. If the backtest ran on yfinance bars, the replay chart must render yfinance bars. Build the chart's datafeed adapter on top of the same `DataflowProvider` interface the engine uses — do not let the chart reach into a separate data path.

**Drawing tools in v1: read-only.** lightweight-charts does not ship persistent drawing tools. In v1 users cannot draw on the chart. If they ask, the answer is "drawings will arrive with the Advanced Charts upgrade — until then, use the Futu app for discretionary markup." Document this explicitly in Settings → Charts so users aren't surprised.

**Migration contract for v2.** When Advanced Charts lands:

- Same indicator set stays default; the extended catalog is opt-in via a Settings toggle (`Show all indicators`), off by default, so the strategy-alignment property is preserved.
- Entry/stop/target lines migrate from `PriceLine` to Advanced Charts shapes. No change to call sites — wrap both behind a `TradingChart` component interface that takes `{entry, stop, target}` props.
- Drawing tools get enabled in Screen 4 and Screen 5. Drawings persist per `{ticker, timeframe}` in local storage.
- Pine Script: not enabled in v2 by default; gate behind an advanced setting so classroom students aren't overwhelmed.

---

## 10. What this unlocks vs. today

| Today | With this design |
|---|---|
| User must already know which ticker to analyze. | Workflow starts from market regime and finds tickers for them. |
| One ticker at a time, one analysis at a time. | Batch analysis across a screened basket. |
| Output is a narrative report + a rating. | Output is a concrete trade plan with entries, stops, sizes, total exposure. |
| No way to validate today's workflow decisions historically. | Walk-forward validates the deterministic trade plan artifact generated by the workflow, using a quant-strict replay engine. |
| `entry_mode` is a config setting the user rarely changes. | Driven by today's regime, with a visible reason. |

---

## 11. Decisions (v1 scope)

1. **Live prices.** Screen 1 streams live. Needs a WebSocket (or polled quote feed) from the market-data provider, with a "Delayed 15 min" fallback banner when live data is unavailable. Engineering impact: the Market screen needs a streaming transport that the other screens don't. Build that layer as a standalone service so Screens 2–5 can stay request/response.
2. **Broker integration: Futu / moomoo.** One-click `Send to Futu` stages orders via the Futu OpenD gateway. Orders are staged, not submitted — the user still hits submit in Futu. Keeps us on the right side of "no autonomous trade execution." CSV export stays as a fallback for users without Futu.
3. **Short selling: enabled by default.** Screen 4 sizes and places short trades just like longs. Gross exposure (longs + shorts) is shown separately from net (longs − shorts). Stops on shorts sit above entry. Requires a margin-enabled Futu account with shorting permissions on the specific ticker — surface that requirement in the confirm dialog, not as a silent failure.
4. **Backtest: quant-strict, no LLM.** Walk-forward and full-history backtests replay a frozen strategy artifact under the deterministic quant engine only — the 5-agent LLM pipeline never runs in backtest mode. This validates the workflow output without re-running the workflow itself, keeps runtimes to minutes instead of hours, and removes run-to-run variance. The UI names this explicitly so users know live LLM-assisted results can diverge.
5. **Portfolio size: per-strategy.** Portfolio size and risk-per-trade are saved with the strategy preset, not globally. A user can have a $10k "small account breakout" preset alongside a $100k "main account swing" preset. Means the saved-strategy schema needs `portfolio_size` and `risk_per_trade` as first-class fields.
6. **Desktop only.** Layout can assume ≥1280px. No responsive breakpoints, no mobile nav, no touch targets. Table-heavy screens (Screens 2 and 4) can use multi-column layouts without collapse.

### Engineering follow-ups from these decisions

- Add a streaming quote layer for Screen 1 (not needed elsewhere).
- Add a Futu OpenD client under `tradingagents/integrations/futu/` — stage-only, never submit. Auth lives in Settings → Broker.
- Short-selling path in `OrderIntentContract` and sizing logic; surface the permission check before the confirm dialog so failure messages are actionable.
- Backtest engine wired to `execution_mode="quant_strict"` at the run level, with a hard guard that the LLM client is never constructed during a backtest run.
- Strategy preset schema: add `portfolio_size`, `risk_per_trade`, and `allow_shorts` fields. Migrate any existing presets by inheriting from a global default on first load.
- Build a shared `TradingChart` React component backed by lightweight-charts in v1. Exposes a library-agnostic prop surface (`{symbol, timeframe, bars, indicators, priceLines, markers}`) so swapping to Advanced Charts in v2 is a single implementation change.
- Build a `ChartDatafeed` adapter that pulls bars from the same `DataflowProvider` the quant engine uses — never a separate data path. Caches per `(symbol, timeframe, range)` in memory with a TTL that matches the engine's cache.
- Submit the TradingView Advanced Charts license application now, in parallel with v1 development. The migration is a component swap, not a rewrite, and can land as soon as the license arrives.
