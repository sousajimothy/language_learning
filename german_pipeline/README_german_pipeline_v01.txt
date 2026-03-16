# -------------------------------------------------- #
# 1. --help
micromamba run -n language_learning_env python cli.py --help
# → shows Commands: init

# 2. init command
micromamba run -n language_learning_env python cli.py init
# → "init: not implemented yet", exit 0

# 3. (optional) install typer after pulling the repo fresh
micromamba run -n language_learning_env pip install typer
# or re-create the env: micromamba env create -f environment.yml


# -------------------------------------------------- #
# 1. First run — creates output/german.db
python cli.py init
# → ✅ DB ready: .../output/german.db
# →    Tables : attempts, examples, vocab_items

# 2. Second run — idempotent, same output, exit 0
python cli.py init

# 3. Custom path
python cli.py init --db /tmp/test.db

# 4. Schema spot-check (copy-paste the inline python from the verification above,
#    or open the DB with any SQLite browser)


# -------------------------------------------------- #
# 1. Fresh DB
python cli.py init

# 2. First import — expect Inserted: 22
python cli.py import-table \
  --path output/golden/2026-02-24_10-23_anki_vocab_export.tsv \
  --source golden_teams_sample_01

# 3. Re-run — expect Inserted: 0, Updated: 0, Skipped: 22
python cli.py import-table \
  --path output/golden/2026-02-24_10-23_anki_vocab_export.tsv \
  --source golden_teams_sample_01


# -------------------------------------------------- #
# 1. Main acceptance check
python cli.py practice --n 3 --source golden_teams_sample_01_xlsx

# 2. Re-run appends (total attempts grows, no error)
python cli.py practice --n 3 --source golden_teams_sample_01_xlsx

# 3. Source-prefix filter
python cli.py practice --n 5 --source-prefix full_vocab

# 4. Default filter (pipeline rows only — excludes anki imports)
python cli.py practice --n 5

# 5. Verify DB content
python -c "
import sqlite3; con = sqlite3.connect('output/german.db')
rows = con.execute('SELECT drill_type, is_correct, ts FROM attempts ORDER BY id DESC LIMIT 5').fetchall()
for r in rows: print(r)
"
