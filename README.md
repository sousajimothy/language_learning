# 🇩🇪 German Language Learning

A personal Streamlit app for building and drilling a German vocabulary database, backed by GPT-4o enrichment and a local SQLite practice engine.

---

## Overview

Raw German words or phrases are pasted in, enriched by GPT-4o (article, English translation, Afrikaans translation, word type / notes), and stored in a local SQLite database. From there, the app supports spaced-repetition-style drilling, performance analytics, targeted study-pack generation, and export to multiple formats.

---

## Pages

| # | Page | Purpose |
|---|------|---------|
| 🏠 | **Home** | Dashboard — live stats (words, attempts, accuracy), quick-start cards |
| 1 | **Vocab Export** | Paste raw words → GPT-4o enrichment → preview cards → export or import to DB |
| 2 | **Import** | Upload a vocabulary file (XLSX / CSV / TSV) and import it into the practice DB |
| 3 | **Practice** | Interactive drill sessions — multiple-choice and typed-answer modes |
| 4 | **Stats** | Performance charts — accuracy over time, drill-type breakdown |
| 5 | **Report** | Worst-performing items report with Plotly charts |
| 6 | **Export Pack** | Generate a focused study pack (TSV / CSV) from weakest items |
| 7 | **AI Agent** | Chat with GPT-4o about your vocabulary DB — find words by theme, surface weak spots |

---

## Export Formats (Vocab Export page)

| Format | Use case |
|--------|----------|
| **TSV** | Anki import — two-column (Front / Back), headerless |
| **CSV** | Excel / Google Sheets / data tools — UTF-8 with BOM |
| **XLSX** | Full vocabulary table — all 5 fields, opens in Excel |
| **Markdown** | GFM pipe table — paste into Obsidian, a README, or any Markdown editor |
| **DOCX** | Formatted Word document — landscape A4, styled table, ready to share or print |
| **PDF** | Formatted PDF — landscape A4, styled table, ready to print or share |

---

## Setup

**Requirements:** [micromamba](https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html) and an OpenAI API key.

```bash
# Create and activate the environment
micromamba env create -f environment.yml
micromamba activate language_learning_env

# Add your API key
echo "OPENAI_API_KEY=sk-..." > .env

# Run the app
micromamba run -n language_learning_env streamlit run app.py
```

---

## Project Structure

```
app.py                      # Streamlit entry point + home page
pages/
  1_Vocab_Export.py         # GPT-4o enrichment + 6-format export
  2_Import.py               # File upload → DB import
  3_Practice.py             # Drill session (MCQ + typed-answer)
  4_Stats.py                # Performance charts
  5_Report.py               # Worst-performers report
  6_Export_Pack.py          # Weak-item study pack generator
  7_AI_Agent.py             # GPT-4o chat agent with DB tool calls
german_pipeline/
  storage.py                # SQLite schema, CRUD, stats queries
  drills.py                 # MCQ and typed-answer drill logic
  grade.py                  # Answer grading helpers
  ingest_export.py          # File parsing + DB import pipeline
  agent.py                  # Agent tool definitions + run_chat()
src/
  anki_vocab_export.py      # Standalone script version of the pipeline
  vocab_export_core.py      # GPT-4o enrichment core (used by pages)
  cache_utils.py            # .xlsx cache validation helpers
assets/
  fonts/                    # Bundled DejaVu Sans TTF (PDF Unicode rendering)
input/
  samples/                  # Sample word lists for testing / golden outputs
output/
  golden/                   # Reference outputs for regression testing
  add/                      # Manually curated TSV files by card type
scripts/
  regen_golden.sh           # Regenerate or verify golden output files
tests/                      # Smoke tests and integration tests
ui_utils.py                 # Shared Streamlit helpers (sidebar, DB, charts)
```

---

## Database Schema

SQLite database at `output/german.db` (gitignored).

| Table | Description |
|-------|-------------|
| `vocab_items` | Core vocabulary — `de`, `de_mit_artikel`, `en`, `af`, `notes`, `word_type`, `source` |
| `attempts` | Every drill attempt — `vocab_id`, `drill_type`, `is_correct`, `latency_ms`, `error_tags` |
| `examples` | GPT-generated example sentences per vocab item |
| `conversations` | AI Agent conversation history |
| `chat_messages` | Individual chat messages with tool-call payloads |

---

## Golden Outputs (Regression Baseline)

`output/golden/` contains reference exports produced from `input/samples/teams_sample_01.txt`. Use them to verify the pipeline hasn't changed behaviour unexpectedly.

```bash
# Regenerate golden files (live API call, incurs cost)
bash scripts/regen_golden.sh

# Structural verification without overwriting
bash scripts/regen_golden.sh --verify
```

Verification checks row count, column names, and source word coverage. Exact diffing is intentionally skipped — GPT-4o is non-deterministic.

<details>
<summary>Manual fallback (if the helper script is not available)</summary>

1. Activate the environment:
   ```bash
   micromamba activate language_learning_env
   ```

2. Copy the contents of `input/samples/teams_sample_01.txt` and paste them as
   the value of `raw_text` in `src/anki_vocab_export.py`.

3. Run the script:
   ```bash
   micromamba run -n language_learning_env python src/anki_vocab_export.py
   ```

4. Copy the timestamped output files into `output/golden/` with the canonical filenames.

</details>

---

## Environment

Dependencies are managed via `environment.yml`. Key packages:

- `streamlit>=1.35` — UI framework
- `openai` — GPT-4o API client
- `python-docx` — DOCX export
- `fpdf2` — PDF export (Unicode via bundled DejaVu Sans)
- `plotly>=5.0` — Charts
- `pandas`, `openpyxl` — Data handling and XLSX I/O

See [CLAUDE.md](CLAUDE.md) for Claude Code–specific guidance on working with this codebase.
