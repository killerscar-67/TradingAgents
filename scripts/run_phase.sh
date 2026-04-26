#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="$ROOT_DIR/tradingagent_venv/bin/python"
PLAN_FILE="$ROOT_DIR/plan-quantStrictDaytradeArchitecture.prompt.md"
UX_PLAN_FILE="$ROOT_DIR/docs/ux-design-daytrade-workflow.md"

die() {
  echo "[run_phase] ERROR: $*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage:
  scripts/run_phase.sh <phase-number>

Behavior:
  - Enforces single canonical Python interpreter: tradingagent_venv/bin/python
  - Runs baseline test suite
  - For manual Copilot phases: prints manual Copilot instruction (Copilot is not headless)
  - For Claude Code/Codex phases: triggers the configured CLI based on phase owner map
  - For phases 9..13: uses docs/ux-design-daytrade-workflow.md as the source plan

Requirements:
  - Quant plan file exists for phases 0..8
  - UX plan file exists for phases 9..13
  - Claude CLI for Claude-owned phases, Codex CLI for Codex-owned phases
EOF
}

require_file() {
  local p="$1"
  [[ -f "$p" ]] || die "Missing file: $p"
}

require_cmd() {
  local c="$1"
  command -v "$c" >/dev/null 2>&1 || die "Missing command: $c"
}

phase_owner() {
  case "$1" in
    0) echo "copilot" ;;
    1) echo "copilot+codex" ;;
    2) echo "claude" ;;
    3) echo "claude" ;;
    4) echo "codex" ;;
    5) echo "codex" ;;
    6) echo "claude" ;;
    7) echo "codex" ;;
    8) echo "manual" ;;
    9) echo "codex" ;;
    10) echo "copilot" ;;
    11) echo "codex" ;;
    12) echo "claude" ;;
    13) echo "copilot" ;;
    *) die "Phase must be 0..13" ;;
  esac
}

phase_prompt() {
  local phase="$1"
  local next=$((phase + 1))

  awk -v p="^${phase}\\. Phase ${phase}:" -v n="^${next}\\. Phase ${next}:" '
    BEGIN { capture=0 }
    $0 ~ p { capture=1 }
    capture { print }
    $0 ~ n && capture { exit }
  ' "$PLAN_FILE"
}

ux_phase_prompt() {
  local phase="$1"
  case "$phase" in
    9)
      cat <<'EOF'
Phase 9: Tooling update plus backend API contracts and route skeletons.
Owner: Codex. Reviewer: Claude Code.
Implement script phase routing for 9..13, define typed web workflow contracts, register route skeletons, and keep the API shapes aligned with docs/ux-design-daytrade-workflow.md.
EOF
      ;;
    10)
      cat <<'EOF'
Phase 10: SQLite storage, settings, watchlists, presets, and history metadata.
Owner: Copilot. Reviewer: Codex.
Implement stdlib SQLite persistence at TRADINGAGENTS_WEB_DB or ~/.tradingagents/web.sqlite3 with idempotent schema initialization and metadata-only storage for workflow artifacts.
EOF
      ;;
    11)
      cat <<'EOF'
Phase 11: Market overview/live quote service, screening, baskets, batch runner, strategy planner, Futu staging, and quant-strict backtest routes.
Owner: Codex. Reviewer: Claude Code.
Wire deterministic orchestration around existing quant, runner, execution, and backtest primitives. Futu must be stage-only. Backtests must force quant_strict and must not construct an LLM client.
EOF
      ;;
    12)
      cat <<'EOF'
Phase 12: Frontend workflow screens and integration with the new APIs.
Owner: Claude Code. Reviewer: Copilot.
Build the desktop-only sidebar workflow: Market, Screen, Analyze, Strategy, Backtest, History, Settings. Add shared state, inherited chips, streaming states, batch cards, strategy table, dialogs, and frontend tests.
EOF
      ;;
    13)
      cat <<'EOF'
Phase 13: End-to-end hardening, legacy archive compatibility, docs/handoffs, and focused regression cleanup.
Owner: Copilot. Reviewer: Codex.
Tighten UX workflow regressions, preserve existing web archive behavior, complete handoff notes, and run focused Python/script/frontend validation.
EOF
      ;;
    *) die "UX phase must be 9..13" ;;
  esac
}

validation_commands() {
  local phase="$1"
  if [[ "$phase" -ge 9 ]]; then
    cat <<EOF
$VENV_PYTHON -m unittest tests.test_web_api tests.test_web_runner tests.test_quant_prefilter tests.test_execution tests.test_backtest -v
$VENV_PYTHON -m unittest tests.test_web_workflow_contracts tests.test_web_api tests.test_web_runner -v
bash -n scripts/review.sh scripts/run_phase.sh
npm --prefix web test
npm --prefix web run build
EOF
  else
    echo "$VENV_PYTHON -m unittest tests.test_quant_tool tests.test_quant_prefilter tests.test_model_validation -v"
  fi
}

build_context() {
  local phase="$1"
  local out="$2"
  local source_plan="$PLAN_FILE"
  if [[ "$phase" -ge 9 ]]; then
    source_plan="$UX_PLAN_FILE"
  fi

  {
    echo "Project root: $ROOT_DIR"
    echo "Phase: $phase"
    echo
    echo "Execution rules:"
    echo "- Use only this Python interpreter: $VENV_PYTHON"
    echo "- Keep changes deterministic and small"
    echo "- Produce handoff file docs/handoffs/phase-${phase}.md"
    echo "- Run validation before completion:"
    validation_commands "$phase" | sed 's/^/  /'
    echo "- Source plan: $source_plan"
    echo
    echo "Relevant prior handoffs (if any):"
    if ls "$ROOT_DIR"/docs/handoffs/phase-*.md >/dev/null 2>&1; then
      for hf in "$ROOT_DIR"/docs/handoffs/phase-*.md; do
        echo "--- $hf ---"
        sed -n '1,220p' "$hf"
        echo
      done
    else
      echo "(none)"
    fi
    echo
    echo "Current phase plan excerpt:"
    if [[ "$phase" -ge 9 ]]; then
      ux_phase_prompt "$phase"
      echo
      echo "UX design source:"
      sed -n '1,220p' "$UX_PLAN_FILE"
    else
      phase_prompt "$phase"
    fi
  } > "$out"
}

if [[ $# -ne 1 ]]; then
  usage
  exit 1
fi

PHASE="$1"
[[ "$PHASE" =~ ^([0-9]|1[0-3])$ ]] || die "Phase must be integer 0..13"

if [[ "$PHASE" -ge 9 ]]; then
  require_file "$UX_PLAN_FILE"
else
  require_file "$PLAN_FILE"
fi
[[ -x "$VENV_PYTHON" ]] || die "Missing interpreter: $VENV_PYTHON"

OWNER="$(phase_owner "$PHASE")"
CONTEXT_FILE="$ROOT_DIR/.phase-${PHASE}-context.txt"
build_context "$PHASE" "$CONTEXT_FILE"

echo "[run_phase] Phase $PHASE owner: $OWNER"
echo "[run_phase] Running baseline tests with canonical venv..."
if [[ "$PHASE" -ge 9 ]]; then
  "$VENV_PYTHON" -m unittest tests.test_web_workflow_contracts tests.test_web_api tests.test_web_runner -v
else
  "$VENV_PYTHON" -m unittest tests.test_quant_tool tests.test_quant_prefilter tests.test_model_validation -v
fi

if [[ "$OWNER" == "copilot" || "$OWNER" == "copilot+codex" ]]; then
  cat <<EOF

[run_phase] Copilot phase requires manual trigger in VS Code chat.
Paste this instruction:

Implement Phase $PHASE from $(basename "$(if [[ "$PHASE" -ge 9 ]]; then echo "$UX_PLAN_FILE"; else echo "$PLAN_FILE"; fi)").
Use only Python interpreter: $VENV_PYTHON.
At completion, write docs/handoffs/phase-$PHASE.md and run:
$(validation_commands "$PHASE")

Context file prepared: $CONTEXT_FILE
EOF
  exit 0
fi

if [[ "$OWNER" == "manual" ]]; then
  cat <<EOF

[run_phase] Phase $PHASE has multi-agent/manual ownership.
Use the prepared context file for the appropriate agent:
$CONTEXT_FILE
EOF
  exit 0
fi

if [[ "$OWNER" == "claude" ]]; then
  require_cmd claude
  echo "[run_phase] Launching Claude Code..."
  claude --print "$(cat "$CONTEXT_FILE")" || die "Claude run failed"
elif [[ "$OWNER" == "codex" ]]; then
  require_cmd codex
  echo "[run_phase] Launching Codex..."
  codex "$(cat "$CONTEXT_FILE")" || die "Codex run failed"
fi

echo "[run_phase] Done. Verify handoff file docs/handoffs/phase-$PHASE.md exists."
