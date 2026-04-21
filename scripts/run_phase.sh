#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="$ROOT_DIR/tradingagent_venv/bin/python"
PLAN_FILE="$ROOT_DIR/plan-quantStrictDaytradeArchitecture.prompt.md"

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
  - For phase 0/1: prints manual Copilot instruction (Copilot is not headless)
  - For phase >=2: triggers Claude Code or Codex based on phase owner map

Requirements:
  - Plan file exists at project root
  - Claude CLI for phases 2/3/6, Codex CLI for phases 4/5
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
    *) die "Phase must be 0..6" ;;
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

build_context() {
  local phase="$1"
  local out="$2"

  {
    echo "Project root: $ROOT_DIR"
    echo "Phase: $phase"
    echo
    echo "Execution rules:"
    echo "- Use only this Python interpreter: $VENV_PYTHON"
    echo "- Keep changes deterministic and small"
    echo "- Produce handoff file docs/handoffs/phase-${phase}.md"
    echo "- Run tests before completion: $VENV_PYTHON -m unittest tests.test_quant_tool tests.test_quant_prefilter tests.test_model_validation -v"
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
    phase_prompt "$phase"
  } > "$out"
}

if [[ $# -ne 1 ]]; then
  usage
  exit 1
fi

PHASE="$1"
[[ "$PHASE" =~ ^[0-6]$ ]] || die "Phase must be integer 0..6"

require_file "$PLAN_FILE"
[[ -x "$VENV_PYTHON" ]] || die "Missing interpreter: $VENV_PYTHON"

OWNER="$(phase_owner "$PHASE")"
CONTEXT_FILE="$ROOT_DIR/.phase-${PHASE}-context.txt"
build_context "$PHASE" "$CONTEXT_FILE"

echo "[run_phase] Phase $PHASE owner: $OWNER"
echo "[run_phase] Running baseline tests with canonical venv..."
"$VENV_PYTHON" -m unittest tests.test_quant_tool tests.test_quant_prefilter tests.test_model_validation -v

if [[ "$OWNER" == "copilot" || "$OWNER" == "copilot+codex" ]]; then
  cat <<EOF

[run_phase] Copilot phase requires manual trigger in VS Code chat.
Paste this instruction:

Implement Phase $PHASE from plan-quantStrictDaytradeArchitecture.prompt.md.
Use only Python interpreter: $VENV_PYTHON.
At completion, write docs/handoffs/phase-$PHASE.md and run:
$VENV_PYTHON -m unittest tests.test_quant_tool tests.test_quant_prefilter tests.test_model_validation -v

Context file prepared: $CONTEXT_FILE
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
