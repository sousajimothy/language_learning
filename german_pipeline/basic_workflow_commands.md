Basic “daily” workflow, assuming you’re using pipeline XLSX exports.

## One-time setup

```bash
python cli.py init
```

## Each time you add new vocab (from your latest full export)

```bash
python cli.py import-latest
python cli.py generate-examples
```

## Daily practice (basic exercises)

Fast default (mixed drills, auto-picks latest pipeline source or falls back to all pipeline vocab if needed):

```bash
python cli.py daily
```

Focused sessions:

```bash
python cli.py drill-articles
python cli.py drill-cloze
python cli.py drill-mcq
```

If you want deterministic sessions (useful for debugging/repeat):

```bash
python cli.py daily --seed 1
```

## Weekly review + targeted pack

```bash
python cli.py weekly-report
python cli.py export-pack
```

## If you want to force a specific dataset

```bash
python cli.py import-table --path output/2026-02-24_10-23_full_vocab_export.xlsx --format pipeline --source my_session_2026_02_24
python cli.py practice --n 15 --mode mixed --source pipeline:my_session_2026_02_24
```

That’s the minimal loop:
**import → generate examples → practice → report/export**.
