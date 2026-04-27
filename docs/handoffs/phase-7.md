# Phase 7 Handoff — Conversational Trade-Review Consultant
Agent: Codex
Date: 2026-04-22

## What was built

- `tradingagents/agents/utils/llm_support.py`: extended the support-only LLM module with a conversation-safe trade-review consultant.
    - `TradeReviewResponse`: frozen advisory response contract with `answer`, `observations`, `follow_up_questions`, `referenced_context_keys`, `blocking`, and `error`.
    - `chat_trade_review(llm, context, messages) -> TradeReviewResponse`: answers trade-review questions from supplied context and conversation history.
- `tests/test_trade_review_consultant.py`: Phase 7 coverage for structured advisory responses, provider failure containment, malformed response containment, executable-field stripping, context-key grounding, prompt construction, and input immutability.

## Contracts exposed to next phase

- `chat_trade_review(llm, context, messages) -> TradeReviewResponse`: support-only consultant entry point. It accepts supplied trade context plus conversation messages and returns advisory text only.
- `TradeReviewResponse`: serializable contract whose `to_dict()` emits only advisory fields. It does not include `rating`, `blocked`, `order_intent`, `risk_gate`, `portfolio_state`, `submit_order`, or other executable mutation fields even if the LLM returns them.

## Config keys added

- None.

## Test command

```
/Users/josephwong/TradingAgents/tradingagent_venv/bin/python -m unittest tests.test_trade_review_consultant tests.test_llm_support -v
/Users/josephwong/TradingAgents/tradingagent_venv/bin/python -m unittest tests.test_quant_tool tests.test_quant_prefilter tests.test_model_validation -v
```

Expected: 13 support/consultant tests OK; 15 required regression tests OK.

## Known limitations / deferred decisions

- The consultant is a module-level helper only; no CLI, graph, or persistent chat session wiring was added.
- It relies on prompt instructions plus output allowlisting. Provider-specific structured-output enforcement and schema retries are deferred.
- `referenced_context_keys` is filtered to keys present in the provided context, but the helper does not independently verify factual claims inside the answer text.

## What the reviewer must focus on

- Verify consultant output is advisory only and cannot mutate order intent, risk gates, fills, or portfolio state.
- Verify malformed/provider responses remain non-blocking `error` contracts.
- Verify prompt-injection attempts in `messages` cannot introduce executable fields into `TradeReviewResponse.to_dict()`.
- Verify no execution, graph, broker, backtest, or portfolio path imports or calls `chat_trade_review()`.
