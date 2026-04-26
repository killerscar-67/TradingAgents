#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  scripts/add_fix_notes.sh <phase-number> <review-file> [title]

Examples:
  scripts/add_fix_notes.sh 0 reviews/phase-0-review.md
  scripts/add_fix_notes.sh 1 reviews/phase-1/review-20260421_153001-a1b2c3d4.md "Post-review fixes"

Behavior:
  - Creates a timestamped fix-notes artifact under docs/handoffs/history/phase-<N>/
  - Appends/updates a "## Fix notes" section in docs/handoffs/phase-<N>.md
  - Records source review file, git commit, and a findings snapshot for traceability
EOF
}

die() {
  echo "[fix_notes] ERROR: $*" >&2
  exit 1
}

if [[ $# -lt 2 || $# -gt 3 ]]; then
  usage
  exit 1
fi

PHASE="$1"
REVIEW_INPUT="$2"
TITLE="${3:-Post-review fixes}"
[[ "$PHASE" =~ ^([0-9]|1[0-3])$ ]] || die "Phase must be integer 0..13"

HANDOFF="$ROOT_DIR/docs/handoffs/phase-${PHASE}.md"
[[ -f "$HANDOFF" ]] || die "Missing handoff file: $HANDOFF"

if [[ "$REVIEW_INPUT" = /* ]]; then
  REVIEW_FILE="$REVIEW_INPUT"
else
  REVIEW_FILE="$ROOT_DIR/$REVIEW_INPUT"
fi
[[ -f "$REVIEW_FILE" ]] || die "Missing review file: $REVIEW_FILE"

RUN_TS="$(date +%Y-%m-%dT%H:%M:%S%z)"
RUN_ID="$(date +%Y%m%d_%H%M%S)"
GIT_SHA="$(git -C "$ROOT_DIR" rev-parse --short HEAD 2>/dev/null || echo "nosha")"

FIX_DIR="$ROOT_DIR/docs/handoffs/history/phase-${PHASE}"
mkdir -p "$FIX_DIR"
FIX_FILE="$FIX_DIR/fix-notes-${RUN_ID}-${GIT_SHA}.md"

REVIEW_REL="${REVIEW_FILE#$ROOT_DIR/}"
FIX_REL="${FIX_FILE#$ROOT_DIR/}"

REQUIRED_FIXES="$(awk '
  /Top 3 required fixes before re-review/ {capture=1; next}
  capture && /^$/ {exit}
  capture && /^[[:space:]]*[0-9]+\./ {sub(/^[[:space:]]*[0-9]+\.[[:space:]]*/, "- "); print}
' "$REVIEW_FILE")"

{
  echo "# Phase ${PHASE} Fix Notes"
  echo ""
  echo "- Title: ${TITLE}"
  echo "- Date: ${RUN_TS}"
  echo "- Commit: ${GIT_SHA}"
  echo "- Source review: ${REVIEW_REL}"
  echo ""
  echo "## Resolved changes"
  if [[ -n "$REQUIRED_FIXES" ]]; then
    echo "$REQUIRED_FIXES"
  else
    echo "- Summarize concrete fixes applied in this pass."
  fi
  echo "- List touched files and key behavior changes."
  echo ""
  echo "## Validation"
  echo "- Add exact test command(s) run after fixes."
  echo "- Add test result summary (pass/fail, counts)."
  echo ""
  echo "## Review findings snapshot"
  sed -n '1,220p' "$REVIEW_FILE"
} > "$FIX_FILE"

if grep -q "^## Fix notes$" "$HANDOFF"; then
  {
    awk -v rel="$FIX_REL" -v ts="$RUN_TS" '
      BEGIN { inserted=0 }
      {
        print
        if ($0 == "## Fix notes" && inserted == 0) {
          print "- " ts " -> " rel
          inserted=1
        }
      }
    ' "$HANDOFF"
  } > "$HANDOFF.tmp"
  mv "$HANDOFF.tmp" "$HANDOFF"
else
  {
    cat "$HANDOFF"
    echo
    echo "## Fix notes"
    echo "- ${RUN_TS} -> ${FIX_REL}"
  } > "$HANDOFF.tmp"
  mv "$HANDOFF.tmp" "$HANDOFF"
fi

echo "[fix_notes] Wrote $FIX_FILE"
echo "[fix_notes] Updated $HANDOFF"
