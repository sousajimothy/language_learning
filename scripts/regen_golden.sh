#!/usr/bin/env bash
# =============================================================================
# scripts/regen_golden.sh
#
# Regenerate (or structurally verify) the golden output files used as a
# regression baseline for the Anki vocab-export pipeline.
#
# Usage:
#   bash scripts/regen_golden.sh             # regen  – overwrite golden files
#   bash scripts/regen_golden.sh --verify    # verify – generate to temp dir,
#                                            #          compare structure only*
#
# * GPT-4o is non-deterministic, so exact-text diffs will almost always differ.
#   --verify checks row count, column names, and source Deutsch values instead.
#
# Requirements:
#   - micromamba with the 'language_learning_env' environment installed
#   - OPENAI_API_KEY available via .env at the repo root OR already exported
#
# Registered input  : input/samples/teams_sample_01.txt
# Registered goldens: output/golden/2026-02-24_10-23_anki_vocab_export.tsv
#                     output/golden/2026-02-24_10-23_full_vocab_export.xlsx
# =============================================================================

set -euo pipefail

# ── Resolve paths relative to the repo root ───────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

INPUT_FILE="$REPO_ROOT/input/samples/teams_sample_01.txt"
GOLDEN_DIR="$REPO_ROOT/output/golden"
GOLDEN_TSV="$GOLDEN_DIR/2026-02-24_10-23_anki_vocab_export.tsv"
GOLDEN_XLSX="$GOLDEN_DIR/2026-02-24_10-23_full_vocab_export.xlsx"
ENV_FILE="$REPO_ROOT/.env"

# ── Argument parsing ──────────────────────────────────────────────────────────
VERIFY_MODE=false
for arg in "$@"; do
  case "$arg" in
    --verify) VERIFY_MODE=true ;;
    *) echo "❌ Unknown argument: $arg" >&2
       echo "   Usage: $0 [--verify]" >&2
       exit 1 ;;
  esac
done

# ── Preflight checks ──────────────────────────────────────────────────────────
if [[ ! -f "$INPUT_FILE" ]]; then
  echo "❌ Input file not found: $INPUT_FILE" >&2
  exit 1
fi

# Load .env if present (exports OPENAI_API_KEY and any other vars)
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  set +a
  echo "✅ Loaded environment from $ENV_FILE"
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "❌ OPENAI_API_KEY is not set." >&2
  echo "   Add it to $REPO_ROOT/.env or export it before running this script." >&2
  exit 1
fi

# ── Determine output paths ────────────────────────────────────────────────────
if [[ "$VERIFY_MODE" == true ]]; then
  WORK_DIR="$(mktemp -d)"
  OUT_TSV="$WORK_DIR/anki_vocab_export.tsv"
  OUT_XLSX="$WORK_DIR/full_vocab_export.xlsx"
  echo "🔍 VERIFY mode — outputs go to temp dir (golden files will NOT change)"
else
  mkdir -p "$GOLDEN_DIR"
  OUT_TSV="$GOLDEN_TSV"
  OUT_XLSX="$GOLDEN_XLSX"
  echo "♻️  REGEN mode — golden files WILL be overwritten"
fi

echo "   Input : $INPUT_FILE"
echo "   TSV   : $OUT_TSV"
echo "   XLSX  : $OUT_XLSX"
echo ""

# ── Export paths for the inline Python runner ─────────────────────────────────
export REGEN_INPUT_FILE="$INPUT_FILE"
export REGEN_TSV_OUT="$OUT_TSV"
export REGEN_XLSX_OUT="$OUT_XLSX"

# ── Run the pipeline ──────────────────────────────────────────────────────────
# NOTE: This inline Python replicates the exact logic from src/anki_vocab_export.py
# but accepts file-based input and writes to fixed output paths.
# Do NOT edit the system_prompt or column mappings here without also updating
# the source script and notebooks to keep behaviour in sync.
micromamba run -n language_learning_env python - <<'PYEOF'
import json
import os
import sys

import pandas as pd
from openai import OpenAI

# ── Paths from environment ────────────────────────────────────────────────────
input_file = os.environ["REGEN_INPUT_FILE"]
tsv_out    = os.environ["REGEN_TSV_OUT"]
xlsx_out   = os.environ["REGEN_XLSX_OUT"]

# ── Read and clean input (mirrors clean_text() in the source script) ──────────
with open(input_file, encoding="utf-8") as fh:
    raw_text = fh.read()

phrases = [line.strip() for line in raw_text.splitlines() if line.strip()]
print(f"Loaded {len(phrases)} phrase(s) from {os.path.basename(input_file)}")

# ── System prompt (kept identical to src/anki_vocab_export.py) ───────────────
system_prompt = """
You are an expert German language tutor and data processor. The user will provide a list of German phrases or words.
Your task is to process each item and return a single JSON object. The JSON object should contain one key, "vocabulary", which is a list of objects.
Each object in the list must contain the following five keys: "deutsch", "deutsch_mit_artikel", "englisch", "afrikaans", and "hinweise".

- `deutsch`: The original German phrase.
- `deutsch_mit_artikel`: If the phrase contains a noun that needs an article, add it (e.g., "Kürbis" -> "der Kürbis"). For full sentences or non-nouns, this can be the same as the "deutsch" field.
- `englisch`: The English translation.
- `afrikaans`: The Afrikaans translation.
- `hinweise`: The part of speech (Wortart), gender (Genus) for nouns, and any other helpful notes.

Do not include any other text, explanations, or markdown formatting outside of the final JSON object.
"""

# ── Call the OpenAI API (mirrors get_vocabulary_data() in the source script) ──
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
print("Calling GPT-4o API…")
try:
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": "\n".join(phrases)},
        ],
        response_format={"type": "json_object"},
    )
    vocabulary_list = json.loads(response.choices[0].message.content)["vocabulary"]
    print(f"✅ Received {len(vocabulary_list)} item(s) from API.")
except Exception as exc:
    print(f"❌ API call failed: {exc}", file=sys.stderr)
    sys.exit(1)

# ── Build DataFrame (mirrors the rename block in the source script) ───────────
df = pd.DataFrame(vocabulary_list)
df.rename(columns={
    "deutsch":             "Deutsch",
    "deutsch_mit_artikel": "Deutsch mit Artikel",
    "afrikaans":           "Afrikaans",
    "englisch":            "Englisch",
    "hinweise":            "Wortart / Genus / Hinweise",
}, inplace=True)

# ── Save XLSX ─────────────────────────────────────────────────────────────────
df.to_excel(xlsx_out, index=False)
print(f"✅ XLSX saved → {xlsx_out}")

# ── Build Anki TSV (mirrors the Anki prep block in the source script) ─────────
df["Front"] = df["Deutsch mit Artikel"]
df["Back"]  = (
    df["Englisch"].fillna("")
    + " — "
    + df["Wortart / Genus / Hinweise"].fillna("")
)
df[["Front", "Back"]].to_csv(
    tsv_out, sep="\t", index=False, header=False, encoding="utf-8"
)
print(f"✅ TSV  saved → {tsv_out}")
PYEOF

# ── Verify mode: structural comparison against current golden files ────────────
if [[ "$VERIFY_MODE" == true ]]; then

  VERIFY_FAILED=false

  echo ""
  echo "── Row-count check ───────────────────────────────────────────────────"
  new_rows=$(wc -l < "$OUT_TSV" | tr -d '[:space:]')
  gold_rows=$(wc -l < "$GOLDEN_TSV" | tr -d '[:space:]')
  echo "  Regenerated : $new_rows rows"
  echo "  Golden      : $gold_rows rows"
  if [[ "$new_rows" -eq "$gold_rows" ]]; then
    echo "  ✅ Row counts match."
  else
    echo "  ❌ Row count mismatch — pipeline may have dropped or duplicated items."
    VERIFY_FAILED=true
  fi

  echo ""
  echo "── XLSX structural check ─────────────────────────────────────────────"
  export REGEN_NEW_XLSX="$OUT_XLSX"
  export REGEN_GOLD_XLSX="$GOLDEN_XLSX"
  micromamba run -n language_learning_env python - <<'PYEOF2'
import os, sys
import pandas as pd

new  = pd.read_excel(os.environ["REGEN_NEW_XLSX"])
gold = pd.read_excel(os.environ["REGEN_GOLD_XLSX"])

# Column names must match exactly
if list(new.columns) != list(gold.columns):
    print(f"  ❌ Column mismatch")
    print(f"     Regenerated : {list(new.columns)}")
    print(f"     Golden      : {list(gold.columns)}")
    sys.exit(1)
print(f"  ✅ Columns match: {list(new.columns)}")

# Row count (already checked via wc -l on the TSV, but double-check XLSX)
if len(new) != len(gold):
    print(f"  ❌ XLSX row count: regenerated={len(new)}, golden={len(gold)}")
    sys.exit(1)
print(f"  ✅ XLSX row count matches ({len(new)} rows).")

# The 'Deutsch' column values should match the source input words
# (case-insensitive strip comparison, order-independent)
new_deutsch  = sorted(new["Deutsch"].str.strip().str.lower().tolist())
gold_deutsch = sorted(gold["Deutsch"].str.strip().str.lower().tolist())
if new_deutsch != gold_deutsch:
    import difflib
    diffs = list(difflib.unified_diff(gold_deutsch, new_deutsch,
                                      lineterm="", n=0))
    print("  ❌ 'Deutsch' values differ from golden:")
    for line in diffs:
        print(f"     {line}")
    sys.exit(1)
print("  ✅ All 'Deutsch' source values match the golden baseline.")
PYEOF2 || VERIFY_FAILED=true

  echo ""
  echo "── TSV content preview (informational, not a pass/fail check) ────────"
  echo "  NOTE: GPT-4o is non-deterministic; translations will differ across"
  echo "  runs. The diff below is shown for human review only."
  echo ""
  diff "$OUT_TSV" "$GOLDEN_TSV" \
    && echo "  (outputs happen to be identical)" \
    || true   # diff exits non-zero when files differ; we treat it as advisory only

  # Clean up temp dir
  rm -rf "$WORK_DIR"

  echo ""
  if [[ "$VERIFY_FAILED" == true ]]; then
    echo "❌ Structural verification FAILED — see details above."
    exit 1
  else
    echo "✅ Structural verification PASSED."
  fi
fi

echo ""
echo "Done."
