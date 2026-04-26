# UX Copy: Analysis Run Screen

> Target user: day-trader or beginner-to-intermediate investor.
> Surface: the screen where a user picks a ticker, a date, and model/run settings before kicking off an agent-driven analysis (CLI today, Phase 9 web UI next).
> Tone: professional plain-language — precise like a terminal, but every piece of jargon is translated in place.

---

## Recommended Copy

- **Primary CTA (idle):** Run analysis
- **Primary CTA (running):** Stop analysis
- **Secondary CTAs:** Save as preset · Load preset · Reset to defaults · Advanced settings
- **Screen intro (empty state, no runs yet):**
  > Ready to analyze. Enter a ticker and a date to get started.
  > Five analyst teams will research fundamentals, news, sentiment, and price action, then debate a recommendation.
- **Ticker field placeholder:** `AAPL, SHOP.TO, 9984.T…`
- **Date field label:** As-of date
- **Run metadata line (below button):** Usually 2–4 minutes depending on the models you picked.

---

## Buttons and CTAs — alternatives

| Option | Copy | Tone | Best for |
|---|---|---|---|
| A (Recommended) | Run analysis | Professional, action-first | Default state. Clear outcome, verb-led. |
| B | Analyze AAPL | Specific | When a ticker is already entered — reinforces what's about to happen. |
| C | Start run | Generic | Only if the screen supports multiple run types and the context is obvious. |

Avoid: Submit · Go · OK · Confirm. They hide the outcome.

Secondary button pairs for destructive actions:

| Context | Confirm | Cancel |
|---|---|---|
| Abort mid-stream | Stop analysis | Keep running |
| Discard unsaved config | Discard changes | Keep editing |
| Clear prefilter cache | Clear cache | Keep cache |

---

## Error and Warning Messages

Pattern: **What happened · Why · How to fix.**

| Trigger | Copy |
|---|---|
| Ticker not found | Can't find "AAPLE." Double-check the symbol. For non-US stocks, include the exchange — e.g., `SHOP.TO` (Toronto), `VOD.L` (London), `9984.T` (Tokyo). |
| Missing API key | Anthropic API key missing. Add it in Settings → Providers, then run again. |
| Rate limit hit | Hit the OpenAI rate limit. Wait about 60 seconds, or switch providers in Settings → Providers. |
| Future date | Analysis date must be today or earlier. Markets haven't closed yet for the date you picked. |
| Non-trading day | No market data for Apr 25, 2026 — markets were closed that day. Try the nearest weekday. |
| Data vendor timeout (soft) | Yahoo Finance is slow to respond. Retrying… |
| Data vendor timeout (hard) | Yahoo Finance didn't return data after 3 tries. Switch to Alpha Vantage in Settings → Data, or try again in a few minutes. |
| Quant signal failed (strict mode) | No trade signal. The quant rule didn't produce a valid setup for this ticker on this date. In `quant_strict` mode, that means no recommendation. Try a different date or switch to `llm_assisted`. |
| Model timeout | The model took too long. Try a lighter "quick think" model in Advanced settings, or reduce debate rounds. |
| Cost warning (pre-run) | This run will use about 45k tokens across 2 models. Continue? |

---

## Empty and Loading States

**Before any run (empty state):**

> **No analyses yet.**
> Pick a ticker and date above, then hit Run analysis. Results will appear here.

**Streaming progress** — shown inline as each phase streams. Keep active phase bolded, completed phases dimmed with a checkmark.

1. Scoring candidates with quant signals…
2. Market analyst — pulling price history and indicators
3. News analyst — gathering headlines
4. Social analyst — reading sentiment
5. Fundamentals analyst — pulling financials
6. Researchers debating — bull vs. bear, round 1 of 2
7. Research manager — weighing the arguments
8. Trader — drafting a proposal
9. Risk team — aggressive, neutral, and conservative review
10. Portfolio manager — final call
11. Done. Compiling the report…

**Waiting-too-long fallback (after 3 min in one phase):**

> Still working on "Researchers debating…" This step can take a minute on deep-think models. You can keep waiting or stop and try again with lighter settings.

---

## Tooltips and Helper Text

| Field | Tooltip |
|---|---|
| Ticker | The stock symbol. For non-US exchanges, add a suffix — e.g., `SHOP.TO` (Toronto), `VOD.L` (London), `9984.T` (Tokyo), `0005.HK` (Hong Kong). |
| As-of date | The date the analysis is run "as of." Agents only see data available up to end of this day — useful for backtests. |
| Execution mode → LLM-assisted | The model reads the full debate and picks the final rating. More nuanced, but results can vary between runs. |
| Execution mode → Quant-strict | A fixed rule — the quant signal — decides the rating. Same inputs always give the same output. Best for backtesting. |
| Deep-think model | Used for slow, careful reasoning (researcher debates, risk review). Pick your most capable model here. |
| Quick-think model | Used for fast, simple tasks (extracting the final rating, summarizing). A cheaper model is fine. |
| Max debate rounds | How many back-and-forths the bull and bear researchers get. More rounds = deeper analysis, but slower and pricier. |
| Entry mode → Auto | Let the system pick breakout or mean-reversion based on current market conditions. |
| Entry mode → Breakout | Force a trend-following setup. Works best in strong, directional markets. |
| Entry mode → Mean reversion | Force a pullback setup. Works best in choppy, range-bound markets. |
| Data vendor | Where price and fundamentals come from. Yahoo Finance is free and works out of the box. Alpha Vantage needs an API key but has better coverage for some markets. |
| Output language | The language of the final report. Internal agent debates always happen in English for consistency. |
| Quant prefilter cache | Scored tickers are cached so re-runs are fast. Cache expires after {ttl} days. Turn off "Use cache" to force a fresh score. |

---

## Rationale

Plain-language unwraps every piece of jargon inline rather than linking to docs — beginners never hit a dead end, and advanced users can still scan for the technical term (`quant_strict`, `mean reversion`) in the same sentence. Error messages name the action the user needs to take next, so failure states don't feel like punishment. Progress messages name the agent that's running so users internalize the pipeline over time — turning streaming into onboarding. CTAs use verb-first outcomes ("Run analysis," "Stop analysis") instead of generic confirmations, matching the action to the label.

## Localization Notes

Ticker suffix examples (`.TO`, `.L`, `.T`, `.HK`) must be preserved as literal characters — do not translate or transliterate. Keep time estimates as ranges ("2–4 minutes") rather than single numbers; localized number formats vary and ranges translate cleanly. "Bull" and "bear" are standard finance terms in most languages but consider a short gloss in FR/DE/JA on first use if the audience skews beginner. Avoid idioms in error messages ("hit a wall," "under the hood") — they expand poorly. Currency symbols should be locale-formatted rather than hard-coded to `$`.
