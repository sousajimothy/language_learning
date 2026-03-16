# Language Learning – Anki Vocab Export

See [CLAUDE.md](CLAUDE.md) for environment setup and the core workflow overview.

---

## Golden outputs (regression baseline)

### What are the golden files?

The files in `output/golden/` are reference outputs that represent the expected
results of the pipeline for a known input. They serve as a regression baseline:
if the pipeline is changed, you can re-run it against the same input and compare
the new output to the golden files to detect unintended changes in behaviour.

| File | Description |
|------|-------------|
| `output/golden/2026-02-24_10-23_anki_vocab_export.tsv` | Anki-ready two-column export |
| `output/golden/2026-02-24_10-23_full_vocab_export.xlsx` | Full vocabulary table (also used as API cache) |

### Which input do they correspond to?

Both golden files were produced from:

```
input/samples/teams_sample_01.txt
```

That file contains a list of German words and phrases (one per line) that were
pasted into the pipeline as `raw_text`.

### How to regenerate the golden outputs

Use the helper script, which reads `input/samples/teams_sample_01.txt` directly
and overwrites the golden files in-place:

```bash
# From the repo root
bash scripts/regen_golden.sh
```

The script will:
1. Load `OPENAI_API_KEY` from `.env` (or use it if already exported)
2. Read and clean `input/samples/teams_sample_01.txt`
3. Call the GPT-4o API with the same prompt used by the main pipeline
4. Write the results directly to `output/golden/`, overwriting both files

> **Note:** Each run makes a live OpenAI API call and will incur usage costs.
> The script does **not** use the `.xlsx` caching logic from the main pipeline
> so that the golden files always reflect a fresh API response.

<details>
<summary>Manual fallback (if the helper script is not available)</summary>

1. Activate the environment:
   ```bash
   micromamba activate language_learning_env
   ```

2. Open `src/anki_vocab_export.py` (or the canonical notebook
   `notebooks/2026-06-26_anki_vocab_export_clean.ipynb`).

3. Copy the contents of `input/samples/teams_sample_01.txt` and paste them as
   the value of `raw_text` in the script/notebook.

4. Run the script:
   ```bash
   micromamba run -n language_learning_env python src/anki_vocab_export.py
   ```
   Or run all cells in the notebook top-to-bottom.

5. The pipeline writes two timestamped files to `output/`:
   ```
   output/YYYY-MM-DD_HH-MM_anki_vocab_export.tsv
   output/YYYY-MM-DD_HH-MM_full_vocab_export.xlsx
   ```

6. Copy them into `output/golden/` with the canonical golden filenames:
   ```bash
   cp output/YYYY-MM-DD_HH-MM_anki_vocab_export.tsv \
      output/golden/2026-02-24_10-23_anki_vocab_export.tsv
   cp output/YYYY-MM-DD_HH-MM_full_vocab_export.xlsx \
      output/golden/2026-02-24_10-23_full_vocab_export.xlsx
   ```
</details>

### How to verify regeneration

Use the `--verify` flag to generate output in a temporary directory and compare
it structurally against the current golden files **without overwriting them**:

```bash
bash scripts/regen_golden.sh --verify
```

The verify run checks:
- **Row count** — same number of vocabulary items as the golden TSV
- **Column names** — XLSX columns are identical to the golden XLSX
- **Deutsch values** — every source German phrase is present in the output
- **TSV diff** — shown as informational output for human review

> **Why not an exact diff?**  GPT-4o is non-deterministic; translations and
> `Hinweise` wording vary between runs. The structural checks above confirm that
> the pipeline is working correctly without being brittle to phrasing changes.

Exit codes: `0` = structural checks passed, `1` = at least one check failed.
