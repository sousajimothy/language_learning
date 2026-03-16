# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

Managed with **micromamba**. Environment name: `language_learning_env`.

```bash
# Create environment
micromamba env create -f environment.yml

# Activate
micromamba activate language_learning_env

# Install a new package (also add it to environment.yml)
micromamba run -n language_learning_env pip install <package>
```

Dependencies: Python 3.11, pandas, openpyxl, ipykernel, openai, python-dotenv.

API key lives in `.env` at the repo root:
```
OPENAI_API_KEY=sk-...
```

## Project Structure

```
src/                  # Standalone script version of the workflow
notebooks/            # Jupyter notebooks (development & production)
output/               # Generated exports (gitignored in practice)
  *.tsv               # Anki-ready two-column exports (timestamped)
  *.xlsx              # Full vocabulary tables (timestamped, used as API cache)
  add/                # Manually curated TSV files by card type
  anki_decks/         # Pre-downloaded .apkg deck files
```

## Core Workflow

The main workflow is in [src/anki_vocab_export.py](src/anki_vocab_export.py) and mirrored in [notebooks/2025-06-26_anki_vocab_export_clean.ipynb](notebooks/2025-06-26_anki_vocab_export_clean.ipynb).

**Pipeline:**
1. User pastes raw German words/phrases into `raw_text`
2. `clean_text()` splits into a list, stripping blank lines
3. `get_vocabulary_data()` calls GPT-4o with a structured JSON prompt, returning 5 fields per phrase: `deutsch`, `deutsch_mit_artikel`, `englisch`, `afrikaans`, `hinweise`
4. Result is saved to a timestamped `.xlsx` (full data) and `.tsv` (Anki import)
5. **Caching**: if the `.xlsx` for the current session already exists, the API call is skipped and data is loaded from disk instead

**Anki card format:**
- **Front**: `Englisch — Wortart / Genus / Hinweise` (e.g. `pumpkin — Noun, masculine`)
- **Back**: `Deutsch mit Artikel` (e.g. `der Kürbis`)

**Output file naming**: `YYYY-MM-DD_HH-MM_anki_vocab_export.tsv` / `..._full_vocab_export.xlsx`

## Notebooks

- `2025-06-26_anki_vocab_export.ipynb` — original notebook, contains legacy cells; do not use as reference
- `2025-06-26_anki_vocab_export_clean.ipynb` — clean version, cells run sequentially top-to-bottom; use this as the canonical reference
