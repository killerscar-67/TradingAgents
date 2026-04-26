# Phase 5 Handoff — LLM Support Modules
Agent: Codex
Date: 2026-04-22

## What was built

- `tradingagents/agents/utils/llm_support.py`: support-only LLM helpers with frozen typed contracts and contained parsing errors.
    - `build_pre_trade_brief(llm, context) -> PreTradeBrief`
    - `watch_anomalies(llm, context) -> AnomalyWatch`
    - `build_post_trade_attribution(llm, context) -> PostTradeAttribution`
    - `annotate_order_intent_with_support(order_intent, pre_trade_brief=None, anomaly_watch=None) -> dict`
- `tests/test_llm_support.py`: Phase 5 coverage for structured pre-trade brief parsing, malformed output containment, binary-only anomaly flags, provider failure containment, and support-only order-intent annotation.

## Contracts exposed to next phase

- `PreTradeBrief`: non-blocking catalyst/event-risk summary. `blocking` is always `False`; parser/provider failures are represented in `error`.
- `AnomalyWatch`: non-blocking anomaly summary with fixed binary flags: `event_risk`, `liquidity_risk`, `data_quality_risk`, and `news_risk`. Non-boolean flag values are rejected and normalized to `False`.
- `PostTradeAttribution`: non-blocking structured trade journal summary with factors and lessons. It is intended for post-fill journaling, not for attachment to live order intents through `annotate_order_intent_with_support()`.
- `annotate_order_intent_with_support(...)`: returns a deep-copied order intent with support payloads under `annotations["llm_support"]`; it does not mutate `rating`, `blocked`, `reason`, risk annotations, or the input object.

## Config keys added

- None.

## Test command

```
/Users/josephwong/TradingAgents/tradingagent_venv/bin/python -m unittest tests.test_llm_support -v
/Users/josephwong/TradingAgents/tradingagent_venv/bin/python -m unittest tests.test_quant_tool tests.test_quant_prefilter tests.test_model_validation -v
```

Expected: 7 Phase 5 support tests OK; 15 required regression tests OK.

## Known limitations / deferred decisions

- The helpers are standalone and not wired into the graph runtime. Callers can invoke them explicitly where support annotations are desired.
- LLM prompts are intentionally minimal and expect a single JSON object. Schema repair, retry logic, and provider-specific structured-output APIs are deferred.
- The anomaly watcher fails closed to all `False` flags on malformed or non-binary output because Phase 5 output must never block or modify execution.
- Post-trade attribution intentionally has a separate lifecycle from order-intent annotations: it should be stored with journals, fills, or review artifacts after execution, not merged into pre-trade order-intent metadata.

## What the reviewer must focus on

- Verify no execution path imports or calls `llm_support.py`.
- Verify malformed LLM responses and provider exceptions are represented as non-blocking `error` fields.
- Verify anomaly flags are strict booleans with no string/number truthiness.
- Verify `annotate_order_intent_with_support()` deep-copies input and only writes under `annotations["llm_support"]`.

## Fix notes
- 2026-04-22T12:40:37+0800 -> docs/handoffs/history/phase-5/fix-notes-20260422_124037-878f800.md
