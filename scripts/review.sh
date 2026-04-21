#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="$ROOT_DIR/tradingagent_venv/bin/python"
OUT_DIR="$ROOT_DIR/reviews"
PROMPT_PATCH_MAX_LINES="${PROMPT_PATCH_MAX_LINES:-1500}"
PROMPT_HANDOFF_MAX_LINES="${PROMPT_HANDOFF_MAX_LINES:-320}"
REVIEW_GATE_SEVERITIES="${REVIEW_GATE_SEVERITIES:-BLOCKER,HIGH}"

die() {
  echo "[review] ERROR: $*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage:
  scripts/review.sh <phase-number> [base-ref]

Examples:
  scripts/review.sh 0 main
  scripts/review.sh 2 origin/main

Behavior:
  - Enforces canonical venv for any validation commands
  - Builds diff against base ref
  - Snapshots the handoff for this run (immutable audit artifact)
  - Validates handoff structure for agent-to-agent transfer
  - Routes reviewer by plan map:
      0,1,4 -> Claude
      2,3,5 -> Copilot (manual)
      6     -> Codex
  - Saves timestamped review artifacts under reviews/phase-<N>/
  - Updates latest aliases for compatibility:
      reviews/phase-<N>-review.md
      reviews/phase-<N>-diff.patch
  - Supports optional merge gate:
      REVIEW_ENFORCE_GATE=1 scripts/review.sh <phase> [base-ref]

Environment variables:
  - REVIEWER_OVERRIDE=...         Force reviewer: claude|codex|copilot
  - REVIEW_ENFORCE_GATE=1         Fail if gated severities appear in review output
  - REVIEW_GATE_SEVERITIES=...    Comma list, default: BLOCKER,HIGH
  - PROMPT_HANDOFF_MAX_LINES=320  Handoff lines included in review prompt
  - PROMPT_PATCH_MAX_LINES=1500   Diff lines included in review prompt
EOF
}

require_cmd() {
  local c="$1"
  command -v "$c" >/dev/null 2>&1 || die "Missing command: $c"
}

reviewer_for_phase() {
  case "$1" in
    0|1|4) echo "claude" ;;
    2|3|5) echo "copilot" ;;
    6) echo "codex" ;;
    *) die "Phase must be 0..6" ;;
  esac
}

scope_for_phase() {
  case "$1" in
    0) echo "Contract completeness; no text parsing for order execution; safe defaults; LLM annotation-only behavior." ;;
    1) echo "Timezone/session correctness; deterministic cache behavior; no stale/open leakage." ;;
    2) echo "Determinism and module boundaries for regime/entry/validation logic." ;;
    3) echo "Sizing math correctness; kill-switch reachability; exposure checks before order intent." ;;
    4) echo "Order lifecycle state machine; idempotency; pre-trade guard ordering; paper slippage fidelity." ;;
    5) echo "LLM support remains non-execution; malformed output safety; binary anomaly flags." ;;
    6) echo "No lookahead bias; realistic friction model; walk-forward leakage checks." ;;
  esac
}

non_goals_for_phase() {
  case "$1" in
    0) echo "Do not redesign trading strategies or add new data vendors." ;;
    1) echo "Do not modify risk sizing, execution logic, or broker adapters." ;;
    2) echo "Do not alter broker order lifecycle or portfolio reconciliation." ;;
    3) echo "Do not change market data ingestion and cache topology." ;;
    4) echo "Do not rework quant signal generation or regime logic semantics." ;;
    5) echo "Do not allow LLM output to affect order submission paths." ;;
    6) echo "Do not change production execution routes; focus on validation only." ;;
  esac
}

validate_handoff() {
  local handoff_file="$1"
  local missing=0
  local required=(
    "## What was built"
    "## Contracts exposed to next phase"
    "## Config keys added"
    "## Test command"
    "## Known limitations / deferred decisions"
    "## What the reviewer must focus on"
    "## Fix notes"
  )

  for section in "${required[@]}"; do
    if ! grep -Fq "$section" "$handoff_file"; then
      echo "[review] Missing handoff section: $section" >&2
      missing=1
    fi
  done

  if [[ "$missing" -ne 0 ]]; then
    die "Handoff is incomplete: $handoff_file"
  fi
}

build_prompt() {
  local reviewer="$1"
  local phase="$2"
  local scope="$3"
  local non_goals="$4"
  local handoff_file="$5"
  local diff_file="$6"
  local prompt_file="$7"

  {
    echo "You are the review agent for a multi-agent software delivery workflow."
    echo "All output must be in English."
    echo ""
    echo "Project root: $ROOT_DIR"
    echo "Execution environment: $VENV_PYTHON"
    echo "Phase: $phase"
    echo "Reviewer: $reviewer"
    echo ""
    echo "Review scope:"
    echo "$scope"
    echo ""
    echo "Non-goals:"
    echo "$non_goals"
    echo ""
    echo "Rules:"
    echo "- Evaluate only based on handoff + patch below."
    echo "- Do not assume unseen code behavior."
    echo "- Prefer minimal corrective changes over broad rewrites."
    echo "- Prioritize interface integrity, deterministic behavior, and no execution leakage from LLM output."
    echo ""
    echo "Required output format:"
    echo "1. Findings ordered by severity: BLOCKER, HIGH, MEDIUM, LOW."
    echo "2. For each finding include: file path, issue, impact, minimal fix."
    echo "3. Merge decision: APPROVE or CHANGES_REQUIRED."
    echo "4. If CHANGES_REQUIRED, list all required fixes."
    echo ""
    echo "Handoff:"
    sed -n "1,${PROMPT_HANDOFF_MAX_LINES}p" "$handoff_file"
    echo ""
    echo "Patch:"
    sed -n "1,${PROMPT_PATCH_MAX_LINES}p" "$diff_file"
  } > "$prompt_file"
}

enforce_gate() {
  local review_file="$1"
  local severities_csv="$2"
  local severities_regex

  severities_regex="$(echo "$severities_csv" | tr ',' '|' | tr -d ' ')"
  if grep -Eiq "(^|[^A-Z])(${severities_regex})([^A-Z]|$)" "$review_file"; then
    die "Merge gate failed due to one or more gated severities in $review_file"
  fi
}

if [[ $# -lt 1 || $# -gt 2 ]]; then
  usage
  exit 1
fi

PHASE="$1"
BASE_REF="${2:-main}"
[[ "$PHASE" =~ ^[0-6]$ ]] || die "Phase must be integer 0..6"

mkdir -p "$OUT_DIR"

REVIEWER="$(reviewer_for_phase "$PHASE")"
if [[ -n "${REVIEWER_OVERRIDE:-}" ]]; then
  case "$REVIEWER_OVERRIDE" in
    claude|codex|copilot) REVIEWER="$REVIEWER_OVERRIDE" ;;
    *) die "REVIEWER_OVERRIDE must be one of: claude, codex, copilot" ;;
  esac
fi
SCOPE="$(scope_for_phase "$PHASE")"
NON_GOALS="$(non_goals_for_phase "$PHASE")"
HANDOFF="$ROOT_DIR/docs/handoffs/phase-${PHASE}.md"

GIT_SHA="$(git -C "$ROOT_DIR" rev-parse --short HEAD 2>/dev/null || true)"
[[ -n "$GIT_SHA" ]] || GIT_SHA="nosha"
RUN_ID="$(date +%Y%m%d_%H%M%S)-${GIT_SHA}"

PHASE_OUT_DIR="$OUT_DIR/phase-${PHASE}"
HANDOFF_HISTORY_DIR="$ROOT_DIR/docs/handoffs/history/phase-${PHASE}"
mkdir -p "$PHASE_OUT_DIR" "$HANDOFF_HISTORY_DIR"

DIFF_FILE="$PHASE_OUT_DIR/diff-${RUN_ID}.patch"
OUT_FILE="$PHASE_OUT_DIR/review-${RUN_ID}.md"
PROMPT_FILE="$PHASE_OUT_DIR/review-prompt-${RUN_ID}.txt"
HANDOFF_SNAPSHOT="$HANDOFF_HISTORY_DIR/handoff-${RUN_ID}.md"

LATEST_DIFF_FILE="$OUT_DIR/phase-${PHASE}-diff.patch"
LATEST_OUT_FILE="$OUT_DIR/phase-${PHASE}-review.md"

require_cmd git
[[ -x "$VENV_PYTHON" ]] || die "Missing interpreter: $VENV_PYTHON"
[[ -f "$HANDOFF" ]] || die "Missing handoff file: $HANDOFF"
validate_handoff "$HANDOFF"

cp "$HANDOFF" "$HANDOFF_SNAPSHOT"
validate_handoff "$HANDOFF_SNAPSHOT"

echo "[review] reviewer=$REVIEWER phase=$PHASE base=$BASE_REF run_id=$RUN_ID"
echo "[review] handoff_snapshot=$HANDOFF_SNAPSHOT"

# Prefer branch phase/<N> if it exists, otherwise compare working tree to base.
if git -C "$ROOT_DIR" show-ref --verify --quiet "refs/heads/phase/${PHASE}"; then
  git -C "$ROOT_DIR" --no-pager diff "$BASE_REF...phase/${PHASE}" > "$DIFF_FILE"
else
  git -C "$ROOT_DIR" --no-pager diff "$BASE_REF...HEAD" > "$DIFF_FILE"
fi

if [[ ! -s "$DIFF_FILE" ]]; then
  echo "[review] No diff found for review." > "$OUT_FILE"
  cp "$OUT_FILE" "$LATEST_OUT_FILE"
  cp "$DIFF_FILE" "$LATEST_DIFF_FILE"
  echo "[review] Wrote $OUT_FILE"
  echo "[review] Updated latest alias $LATEST_OUT_FILE"
  exit 0
fi

build_prompt "$REVIEWER" "$PHASE" "$SCOPE" "$NON_GOALS" "$HANDOFF_SNAPSHOT" "$DIFF_FILE" "$PROMPT_FILE"

if [[ "$REVIEWER" == "claude" ]]; then
  require_cmd claude
  claude --print "$(cat "$PROMPT_FILE")" > "$OUT_FILE"
elif [[ "$REVIEWER" == "codex" ]]; then
  require_cmd codex
  codex review - < "$PROMPT_FILE" > "$OUT_FILE"
else
  cat <<EOF > "$OUT_FILE"
Copilot review phase (manual):
1. Open VS Code Copilot Chat in this workspace.
2. Ask: "Review phase $PHASE changes. Scope: $SCOPE. Output in English."
3. Provide these artifacts:
   - docs/handoffs/phase-$PHASE.md
   - reviews/phase-$PHASE-diff.patch
4. Require this format:
   - Findings by severity (BLOCKER/HIGH/MEDIUM/LOW)
   - Merge decision: APPROVE or CHANGES_REQUIRED
EOF
fi

echo "[review] Wrote $OUT_FILE"
cp "$OUT_FILE" "$LATEST_OUT_FILE"
cp "$DIFF_FILE" "$LATEST_DIFF_FILE"
echo "[review] Updated latest alias $LATEST_OUT_FILE"
echo "[review] Updated latest alias $LATEST_DIFF_FILE"

if [[ "${REVIEW_ENFORCE_GATE:-0}" == "1" ]]; then
  enforce_gate "$OUT_FILE" "$REVIEW_GATE_SEVERITIES"
  echo "[review] Gate passed"
fi
