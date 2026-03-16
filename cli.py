"""
cli.py — Command-line entrypoint for the German practice pipeline.

Usage:
    python cli.py --help
    python cli.py init [--db PATH]
    python cli.py import-table --path FILE --source LABEL [--format {pipeline,anki}] [--db PATH]
      FILE may be .tsv / .csv / .xlsx (pipeline mode) or .tsv/.csv (anki mode)
      Stored source label is automatically prefixed: pipeline:<LABEL> or anki:<LABEL>
    python cli.py practice    [--db PATH] [--n N] [--source LABEL] [--source-prefix PREFIX]
                              [--seed INT] [--mode MODE]
    python cli.py stats      [--db PATH] [--days N] [--source LABEL] [--source-prefix PREFIX]
    python cli.py report     [--db PATH] [--days N] [--n N] [--source LABEL] [--source-prefix PREFIX]
    python cli.py export-pack       [--db PATH] [--days N] [--worst-n N] [--missed-n N]
                                   [--min-attempts N] [--source LABEL] [--source-prefix PREFIX]
                                   [--alltime-scope {filtered,global}] [--out-dir DIR]
    python cli.py generate-examples [--db PATH] [--max-per-item N] [--limit N]
                                   [--source LABEL] [--source-prefix PREFIX] [--dry-run]

Source-label convention
-----------------------
``import-table`` prepends the format name as a namespace prefix before
storing in the DB, unless the label already begins with a known prefix:

    --format pipeline --source teams_01   →  stored as ``pipeline:teams_01``
    --format anki     --source deck_A     →  stored as ``anki:deck_A``

The ``practice`` command defaults to ``source LIKE 'pipeline:%'`` so that
structured (richer) items are practised by default.  Use ``--source-prefix``
to change this, e.g. ``--source-prefix anki:`` or ``--source-prefix ""``
for everything.
"""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import random
import re
import time
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

import typer

from german_pipeline import drills
from german_pipeline import grade as grade_module
from german_pipeline import ingest_export
from german_pipeline import storage

app = typer.Typer(
    name="german-pipeline",
    help="German vocabulary practice pipeline CLI.",
    add_completion=False,
    no_args_is_help=True,
)

_DEFAULT_DB = Path("output/german.db")

# Glob patterns for file discovery
_FULL_VOCAB_GLOB          = "*_full_vocab_export.xlsx"   # used by import-latest
_DEFAULT_PIPELINE_PATTERN = "*_full_vocab_export.xlsx"
_DEFAULT_ANKI_PATTERN     = "*_anki_vocab_export.tsv"

# Source-label prefixes used to namespace imports by format
_KNOWN_PREFIXES: tuple[str, ...] = ("pipeline:", "anki:")


def _hash_file(path: Path) -> Optional[str]:
    """Return the SHA-256 hex digest of *path*'s contents, or ``None`` on error.

    Reads the file in 64 KiB chunks to avoid loading large files into memory.
    Returns ``None`` if the file cannot be read (permissions, race conditions,
    etc.) so callers can gracefully fall back to the path/mtime dedup key.
    """
    try:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


class ImportFormat(str, Enum):
    """Explicit format selector for ``import-table``."""
    pipeline = "pipeline"
    anki     = "anki"


class PracticeMode(str, Enum):
    """Drill-type focus mode for ``practice`` sessions."""
    mixed    = "mixed"
    translate = "translate"
    articles  = "articles"
    cloze     = "cloze"
    mcq      = "mcq"


class AllTimeScope(str, Enum):
    """Controls whether the most-missed all-time query in ``export-pack``
    applies the same source filter as the worst-items query, or spans all
    sources globally.
    """
    filtered     = "filtered"   # same source/source-prefix filter as worst-items
    global_      = "global"     # no source filter — truly all-time, all sources


class DeriveSource(str, Enum):
    """Strategy for deriving a source label from a file path in ``import-dir``."""
    stem     = "stem"      # file stem (basename without extension)
    relative = "relative"  # relative path from --dir, separators replaced by "__"


#: Maps each :data:`PracticeMode` to the ``allowed_types`` set forwarded to
#: :func:`drills.pick_drill_with_pool`.  ``None`` means no restriction.
_MODE_ALLOWED_TYPES: dict[PracticeMode, set[str] | None] = {
    PracticeMode.mixed:    None,
    PracticeMode.translate: {"en_to_de"},
    PracticeMode.articles:  {"article", "mcq_article"},
    PracticeMode.cloze:     {"cloze"},
    PracticeMode.mcq:       {"mcq_en_to_de", "mcq_article"},
}


def _prefixed_source(source: str, fmt: ImportFormat) -> str:
    """Return *source* with a ``'<fmt>:'`` namespace prefix.

    If *source* already starts with a known prefix it is returned unchanged
    to prevent double-prefixing (e.g. re-importing the same file).
    """
    if any(source.startswith(p) for p in _KNOWN_PREFIXES):
        return source
    return f"{fmt.value}:{source}"


# ---------------------------------------------------------------------------
# --since parsing helper
_SINCE_RELATIVE_RE = re.compile(r"^(\d+)([dh])$")

_SINCE_HELP_EXAMPLES = (
    "Accepted formats:\n"
    "  Relative : 7d, 48h\n"
    "  Date     : 2026-02-20\n"
    "  Datetime : 2026-02-20T14:30  or  2026-02-20T14:30:00"
)


def _parse_since(since: str, tz: str) -> float:
    """Parse a ``--since`` value into a Unix-epoch cutoff (seconds, float).

    *tz* is ``"local"`` or ``"utc"`` and controls how bare dates/datetimes
    are interpreted.  Relative offsets (``"7d"``, ``"48h"``) are always
    relative to the current UTC instant.

    Raises :class:`ValueError` with a human-readable message when the value
    cannot be parsed.
    """
    s = since.strip()

    # ── Relative: Nd or Nh ────────────────────────────────────────────────
    m = _SINCE_RELATIVE_RE.match(s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = timedelta(days=n) if unit == "d" else timedelta(hours=n)
        return (datetime.now(timezone.utc) - delta).timestamp()

    # ── Absolute: date or datetime ────────────────────────────────────────
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            break
        except ValueError:
            continue
    else:
        raise ValueError(
            f"Cannot parse --since value: {since!r}\n   {_SINCE_HELP_EXAMPLES}"
        )

    # Attach timezone: naive datetime.timestamp() uses local time (Python 3
    # guarantee), which is exactly what we want for --since-tz local.
    if tz == "utc":
        dt = dt.replace(tzinfo=timezone.utc)
    # For local, leave dt naive — timestamp() will treat it as local time.
    return dt.timestamp()


# Bulk-import helpers  (used by import-dir; import-table/import-latest kept as-is)
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class _ImportResult:
    """Return value from :func:`_import_one_file`."""
    already_imported: bool = False
    rows_read:        int  = 0
    inserted:         int  = 0
    updated:          int  = 0
    skipped_rows:     int  = 0   # row-level duplicates within the file


def _import_exists(
    con: "sqlite3.Connection",
    source: str,
    file_hash: Optional[str],
    file_path: str,
    file_mtime: float,
) -> bool:
    """Return ``True`` if this file is already recorded in the imports ledger.

    Uses ``(source, file_hash)`` as the primary dedup key when the hash is
    available, falling back to ``(source, file_path, file_mtime)`` otherwise.
    """
    if file_hash is not None:
        return con.execute(
            "SELECT 1 FROM imports WHERE source = ? AND file_hash = ? LIMIT 1",
            (source, file_hash),
        ).fetchone() is not None
    return con.execute(
        "SELECT 1 FROM imports"
        " WHERE source = ? AND file_path = ? AND file_mtime = ? LIMIT 1",
        (source, file_path, file_mtime),
    ).fetchone() is not None


def _derive_label(path: Path, base_dir: Path, strategy: DeriveSource) -> str:
    """Return the raw (unprefixed) source label for *path*.

    * ``stem``     — file stem (basename without extension).
    * ``relative`` — path relative to *base_dir* with OS separators replaced
                     by ``"__"``, extension included (ensures uniqueness in
                     recursive scans).
    """
    if strategy == DeriveSource.stem:
        return path.stem
    rel = path.relative_to(base_dir)
    return str(rel).replace("\\", "__").replace("/", "__")


def _import_one_file(
    con: "sqlite3.Connection",
    path: Path,
    fmt: ImportFormat,
    stored_source: str,
) -> _ImportResult:
    """Import a single file, checking the ledger for duplicates first.

    Returns an :class:`_ImportResult`.  Raises :class:`ValueError` if the
    file cannot be parsed (caller decides whether to abort or continue).
    """
    file_hash  = _hash_file(path)
    file_mtime = path.stat().st_mtime

    # Check ledger before touching the file contents.
    if _import_exists(con, stored_source, file_hash, str(path.resolve()), file_mtime):
        return _ImportResult(already_imported=True)

    # Parse (raises ValueError on bad format/missing headers/etc.)
    rows = ingest_export.read_table(path, fmt=fmt.value)
    if not rows:
        return _ImportResult(already_imported=False, rows_read=0)

    inserted, updated = ingest_export.upsert_vocab_items(con, rows, stored_source)
    storage.record_import(
        con,
        ts=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        file_path=str(path.resolve()),
        file_mtime=file_mtime,
        file_hash=file_hash,
        format=fmt.value,
        source=stored_source,
        rows_read=len(rows),
        inserted=inserted,
        updated=updated,
        skipped=len(rows) - inserted - updated,
    )
    return _ImportResult(
        already_imported=False,
        rows_read=len(rows),
        inserted=inserted,
        updated=updated,
        skipped_rows=len(rows) - inserted - updated,
    )


# ---------------------------------------------------------------------------
# Shared CLI helpers
# ---------------------------------------------------------------------------

def _validate_source_opts(
    source: Optional[str], source_prefix: Optional[str]
) -> None:
    """Exit with an error if both source filter options are given."""
    if source and source_prefix:
        typer.echo(
            "❌ --source and --source-prefix are mutually exclusive.", err=True
        )
        raise typer.Exit(code=1)


def _cutoff_iso(days: int) -> str:
    """Return an ISO-8601 UTC cutoff timestamp *days* ago.

    Uses the same ``'T'`` separator and ``'+00:00'`` suffix as the ``ts``
    values stored by the practice command, ensuring string comparisons in
    SQLite are byte-accurate.
    """
    return (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).replace(microsecond=0).isoformat()


def _trunc(s: Optional[str], width: int) -> str:
    """Truncate *s* to *width* characters, appending '…' if cut."""
    s = s or ""
    return s if len(s) <= width else s[: width - 1] + "…"


def _fmt_ts(ts: Optional[str]) -> str:
    """Format an ISO timestamp as 'YYYY-MM-DD', or '—' if ``None``."""
    return ts[:10] if ts else "—"


def _fmt_rate(rate: float) -> str:
    """Format a 0.0–1.0 rate as a whole-percent string: '68%'."""
    return f"{rate * 100:.0f}%"


def _print_stats_block(s: dict, days: int, header: str = "📊 Practice stats") -> None:
    """Render the summary metrics block shared by stats and report."""
    att = s["attempts_count"]
    nm  = s["near_miss_count"]
    nm_note = (
        f"({_fmt_rate(s['near_miss_rate'])} of attempts)" if att else "(—)"
    )
    typer.echo(
        f"\n{header}  [last {days} days]\n"
        f"   Source filter  : {s['filter_label']}\n"
        f"   {'─' * 38}\n"
        f"   Vocab items    : {s['vocab_count']}\n"
        f"   Attempts       : {att}\n"
        f"   Accuracy       : {_fmt_rate(s['accuracy'])}\n"
        f"   Near misses    : {nm}  {nm_note}\n"
        f"   Last attempt   : {_fmt_ts(s['last_seen'])}\n"
    )


# Column widths for the worst-items table
_WDE = 38   # de_display
_WEN = 30   # en


def _print_worst_items(rows: list[dict], days: int, n: int) -> None:
    """Render the worst-N items table."""
    header = (
        f"{'#':>2}  {'ID':>4}  {'de':<{_WDE}}  {'en':<{_WEN}}  "
        f"{'acc':>4}  {'att':>3}  {'NM':>3}  last seen"
    )
    sep = "─" * len(header)
    typer.echo(f"Worst {n} items  [last {days} days]")
    typer.echo(sep)
    typer.echo(header)
    typer.echo(sep)
    if not rows:
        typer.echo("   (no data yet — run some practice sessions first)")
    for rank, row in enumerate(rows, start=1):
        typer.echo(
            f"{rank:>2}  {row['id']:>4}  "
            f"{_trunc(row['de_display'], _WDE):<{_WDE}}  "
            f"{_trunc(row['en'], _WEN):<{_WEN}}  "
            f"{row['acc_window']:>4.2f}  "
            f"{row['attempts_window']:>3}  "
            f"{row['near_miss_window']:>3}  "
            f"{_fmt_ts(row['last_seen'])}"
        )
    typer.echo("")


# Column widths for the most-missed table
_WDE_MM = 38


def _print_most_missed(rows: list[dict]) -> None:
    """Render the all-time most-missed add-on table."""
    from german_pipeline.storage import _MOST_MISSED_MIN_ATTEMPTS
    header = (
        f"{'#':>2}  {'ID':>4}  {'de':<{_WDE_MM}}  "
        f"{'misses':>6}  {'total':>5}  {'acc':>6}"
    )
    sep = "─" * len(header)
    typer.echo(
        f"Most missed  [all time, top {len(rows) or 5}, "
        f"≥{_MOST_MISSED_MIN_ATTEMPTS} attempts]"
    )
    typer.echo(sep)
    typer.echo(header)
    typer.echo(sep)
    if not rows:
        typer.echo(
            f"   (no items yet with ≥{_MOST_MISSED_MIN_ATTEMPTS} attempts)"
        )
    for rank, row in enumerate(rows, start=1):
        typer.echo(
            f"{rank:>2}  {row['id']:>4}  "
            f"{_trunc(row['de_display'], _WDE_MM):<{_WDE_MM}}  "
            f"{row['miss_count']:>6}  "
            f"{row['total_attempts']:>5}  "
            f"{_fmt_rate(row['acc_alltime']):>6}"
        )
    typer.echo("")


def _choose_focus_mode(metrics: dict) -> tuple:
    """Apply the focus heuristic and return ``(mode, n, rationale)``."""
    art_rate = metrics["article_error_rate"]
    nm_rate  = metrics["near_miss_rate"]
    acc      = metrics["acc"]
    art_att  = metrics["article_attempts"]

    if art_att >= 5 and art_rate >= 0.25:
        return PracticeMode.articles, 15, f"high article error rate ({art_rate:.0%} ≥ 25%)"
    if nm_rate >= 0.20:
        return PracticeMode.cloze, 10, f"high near-miss rate ({nm_rate:.0%} ≥ 20%)"
    if acc < 0.70:
        return PracticeMode.translate, 15, f"low overall accuracy ({acc:.0%} < 70%)"
    return PracticeMode.mixed, 15, "no specific weakness detected"


def _print_focus_summary(
    metrics: dict, days: int, source: str,
    mode: "PracticeMode", n: int, rationale: str,
) -> None:
    """Render the focus-analysis metrics block."""
    att      = metrics["attempts"]
    nm       = metrics["near_miss_count"]
    nm_rate  = metrics["near_miss_rate"]
    art      = metrics["article_attempts"]
    art_w    = metrics["article_wrong"]
    art_rate = metrics["article_error_rate"]

    nm_note  = f"({_fmt_rate(nm_rate)} of attempts)" if att  else "(—)"
    art_note = f"({_fmt_rate(art_rate)} error rate)"  if art else "(—)"

    typer.echo(
        f"\n📈 Focus analysis  [last {days} days, source: {source}]\n"
        f"   {'─' * 46}\n"
        f"   Attempts         : {att}\n"
        f"   Accuracy         : {_fmt_rate(metrics['acc'])}\n"
        f"   Near misses      : {nm}  {nm_note}\n"
        f"   Article attempts : {art}\n"
        f"   Article errors   : {art_w}  {art_note}\n"
        f"\n▶ Chosen mode: {mode.value}  [{n} questions]  — {rationale}\n"
    )


def _auto_resolve_source(con, source, source_prefix):
    """Auto-select the latest pipeline source when no filter is provided.

    If both *source* and *source_prefix* are ``None``:

    1. Resolve the most recently imported pipeline source (prefers imports
       ledger, falls back to ``vocab_items``).
    2. Check whether ``vocab_items`` has any rows for that source.

       * **Has rows** → return ``(latest_source, None)`` and print
         ``Using source: …``.
       * **Empty** (the import was all duplicates / inserted=0) → fall back
         to ``source_prefix='pipeline:'`` (all pipeline vocab) and print a
         one-line note explaining why.

    If either *source* or *source_prefix* is already set by the caller, they
    are returned unchanged with no auto-resolution or note printed.

    Exits with code 1 if no pipeline sources exist at all.
    """
    if source is None and source_prefix is None:
        latest = storage.get_latest_pipeline_source(con)
        if latest is None:
            typer.echo(
                "❌ No pipeline sources found in DB.  "
                "Run `python cli.py import-table --format pipeline ...` first.",
                err=True,
            )
            raise typer.Exit(code=1)
        typer.echo(f"Using source: {latest}")
        if storage.count_vocab_for_source(con, latest) == 0:
            typer.echo(
                "   Note: latest import contained only duplicates; "
                "using all pipeline vocab (--source-prefix pipeline:) for practice/stats/report."
            )
            return None, "pipeline:"
        return latest, None
    return source, source_prefix


def _parse_mcq_choice(raw: str, n_choices: int) -> int | None:
    """Parse a user's MCQ response to a 0-based choice index.

    Accepts letter labels (``A``–``D``, case-insensitive) or numeric labels
    (``1``–``4``).  Returns ``None`` for any unrecognised input.
    """
    r = raw.strip().upper()
    # Letter input: A / B / C / D
    if len(r) == 1 and r in "ABCD"[:n_choices]:
        return ord(r) - ord("A")
    # Numeric input: 1 / 2 / 3 / 4
    if r.isdigit():
        idx = int(r) - 1
        if 0 <= idx < n_choices:
            return idx
    return None


@app.callback()
def _callback() -> None:
    """German vocabulary practice pipeline CLI."""


@app.command("init")
def init(
    db: Path = typer.Option(
        _DEFAULT_DB,
        "--db",
        help="Path to the SQLite database file to create or re-use.",
        show_default=True,
    ),
) -> None:
    """Initialise the practice-pipeline database (creates tables if needed)."""
    db.parent.mkdir(parents=True, exist_ok=True)

    con = storage.connect(db)
    try:
        storage.init_db(con)
        tables = storage.list_tables(con)
    finally:
        con.close()

    typer.echo(f"✅ DB ready: {db.resolve()}")
    typer.echo(f"   Tables : {', '.join(tables)}")


@app.command("import-table")
def import_table(
    path: Path = typer.Option(
        ...,
        "--path",
        help="File to import (.tsv, .csv, or .xlsx). Must exist.",
    ),
    source: str = typer.Option(
        ...,
        "--source",
        help=(
            "Short provenance label (e.g. 'teams_01').  "
            "The format name is automatically prepended as a namespace prefix "
            "before storing (e.g. 'pipeline:teams_01'), unless the label "
            "already starts with a known prefix."
        ),
    ),
    fmt: ImportFormat = typer.Option(
        ImportFormat.pipeline,
        "--format",
        help=(
            "Input file format.\n\n"
            "'pipeline' (default): requires a header row containing at least "
            "'Deutsch' and 'Englisch'. Supports .tsv, .csv, and .xlsx. "
            "Full preferred set: Deutsch | Deutsch mit Artikel | Englisch | "
            "Afrikaans | Wortart / Genus / Hinweise. "
            "Extra columns (e.g. Front, Back) are ignored. "
            "Common header variants are normalised automatically "
            "(e.g. 'English' → 'Englisch', 'Wortart/Genus/Hinweise' → canonical form). "
            "Errors with detected vs. missing headers if required columns are absent.\n\n"
            "'anki': expects a headerless two-column TSV/CSV (Front / Back). "
            "Back is stored verbatim — no em-dash parsing. "
            "Not supported for .xlsx. "
            "Errors if any non-empty row has a column count other than 2."
        ),
        show_default=True,
    ),
    db: Path = typer.Option(
        _DEFAULT_DB,
        "--db",
        help="Path to the SQLite database file.",
        show_default=True,
    ),
) -> None:
    """Import a TSV/CSV/XLSX vocabulary file into the practice-pipeline DB."""
    if not path.exists():
        typer.echo(f"❌ File not found: {path}", err=True)
        raise typer.Exit(code=1)

    # ── Hash + mtime (used for imports ledger; computed before file parse) ─
    file_hash  = _hash_file(path)
    file_mtime = path.stat().st_mtime

    # ── Read and validate file ────────────────────────────────────────────
    try:
        rows = ingest_export.read_table(path, fmt=fmt.value)
    except ValueError as exc:
        typer.echo(f"❌ {exc}", err=True)
        raise typer.Exit(code=1)

    if not rows:
        typer.echo("⚠️  No rows found in the file — nothing to import.")
        raise typer.Exit(code=0)

    # ── Apply source-label convention ─────────────────────────────────────
    stored_source = _prefixed_source(source, fmt)

    # ── Connect (and ensure schema exists) ────────────────────────────────
    db.parent.mkdir(parents=True, exist_ok=True)
    con = storage.connect(db)
    try:
        storage.init_db(con)   # idempotent — safe even if tables already exist
        inserted, updated = ingest_export.upsert_vocab_items(con, rows, stored_source)
        total = con.execute("SELECT COUNT(*) FROM vocab_items").fetchone()[0]
        # ── Record in imports ledger (idempotent) ──────────────────────────
        storage.record_import(
            con,
            ts=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            file_path=str(path.resolve()),
            file_mtime=file_mtime,
            file_hash=file_hash,
            format=fmt.value,
            source=stored_source,
            rows_read=len(rows),
            inserted=inserted,
            updated=updated,
            skipped=len(rows) - inserted - updated,
        )
    finally:
        con.close()

    # ── Report ────────────────────────────────────────────────────────────
    typer.echo(f"✅ Import complete: {path.name}  [format={fmt.value}]")
    typer.echo(f"   Source label : {stored_source}")
    typer.echo(f"   Rows read    : {len(rows)}")
    typer.echo(f"   Inserted     : {inserted}")
    typer.echo(f"   Updated      : {updated}")
    typer.echo(f"   Skipped (dup): {len(rows) - inserted - updated}")
    typer.echo(f"   Total in DB  : {total}")


@app.command("import-latest")
def import_latest(
    db: Path = typer.Option(
        _DEFAULT_DB,
        "--db",
        help="Path to the SQLite database file.",
        show_default=True,
    ),
    dir: Path = typer.Option(
        Path("output"),
        "--dir",
        help=f"Directory to search for {_FULL_VOCAB_GLOB} files.",
        show_default=True,
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print the file that would be imported without modifying the DB.",
        is_flag=True,
    ),
) -> None:
    """Import the newest *_full_vocab_export.xlsx from --dir (idempotent)."""
    # ── Locate candidates ─────────────────────────────────────────────────
    if not dir.is_dir():
        typer.echo(f"❌ Directory not found: {dir}", err=True)
        raise typer.Exit(code=1)

    candidates = sorted(
        dir.glob(_FULL_VOCAB_GLOB),
        key=lambda p: (p.stat().st_mtime, p.stem),
        reverse=True,
    )

    if not candidates:
        typer.echo(
            f"❌ No files matching '{_FULL_VOCAB_GLOB}' found in {dir}.\n"
            f"   Run the vocab export pipeline first to generate a full_vocab_export.xlsx.",
            err=True,
        )
        raise typer.Exit(code=1)

    path = candidates[0]
    stem = path.stem   # e.g. "2025-07-19_12-57_full_vocab_export"
    stored_source = _prefixed_source(stem, ImportFormat.pipeline)

    # ── Hash + mtime (computed before dry-run exit so they are always ready) ─
    file_hash  = _hash_file(path)
    file_mtime = path.stat().st_mtime

    # ── Dry-run ───────────────────────────────────────────────────────────
    if dry_run:
        typer.echo(f"Would import : {path}")
        typer.echo(f"Source label : {stored_source}")
        raise typer.Exit(code=0)

    # ── Connect and init DB (idempotent) ──────────────────────────────────
    db.parent.mkdir(parents=True, exist_ok=True)
    con = storage.connect(db)
    try:
        storage.init_db(con)

        # ── Dedupe guard — check imports ledger first, vocab_items fallback ─
        already = con.execute(
            "SELECT 1 FROM imports WHERE source = ? LIMIT 1",
            (stored_source,),
        ).fetchone()
        if not already:
            # Legacy fallback: source may have been imported before the ledger
            # existed (pre-Step-14 databases).
            already = con.execute(
                "SELECT 1 FROM vocab_items WHERE source = ? LIMIT 1",
                (stored_source,),
            ).fetchone()
        if already:
            typer.echo(f"Already imported: {stored_source}  (from {path})")
            raise typer.Exit(code=0)

        # ── Parse file ─────────────────────────────────────────────────────
        try:
            rows = ingest_export.read_table(path, fmt="pipeline")
        except ValueError as exc:
            typer.echo(f"❌ {exc}", err=True)
            raise typer.Exit(code=1)

        if not rows:
            typer.echo("⚠️  No rows found in the file — nothing to import.")
            raise typer.Exit(code=0)

        # ── Upsert ─────────────────────────────────────────────────────────
        inserted, updated = ingest_export.upsert_vocab_items(con, rows, stored_source)
        total = con.execute("SELECT COUNT(*) FROM vocab_items").fetchone()[0]

        # ── Record in imports ledger (always, even when inserted=0) ────────
        storage.record_import(
            con,
            ts=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            file_path=str(path.resolve()),
            file_mtime=file_mtime,
            file_hash=file_hash,
            format="pipeline",
            source=stored_source,
            rows_read=len(rows),
            inserted=inserted,
            updated=updated,
            skipped=len(rows) - inserted - updated,
        )

    finally:
        con.close()

    # ── Report ────────────────────────────────────────────────────────────
    typer.echo(f"✅ Import complete: {path.name}")
    typer.echo(f"   Source label : {stored_source}")
    typer.echo(f"   Rows read    : {len(rows)}")
    typer.echo(f"   Inserted     : {inserted}")
    typer.echo(f"   Updated      : {updated}")
    typer.echo(f"   Skipped (dup): {len(rows) - inserted - updated}")
    typer.echo(f"   Total in DB  : {total}")


@app.command("import-dir")
def import_dir(
    dir: Path = typer.Option(
        ...,
        "--dir",
        help="Directory to scan for matching files.",
    ),
    fmt: ImportFormat = typer.Option(
        ...,
        "--format",
        help="Input file format: 'pipeline' (.xlsx/.csv/.tsv) or 'anki' (.tsv/.csv).",
    ),
    db: Path = typer.Option(
        _DEFAULT_DB,
        "--db",
        help="Path to the SQLite database file.",
        show_default=True,
    ),
    pattern: Optional[str] = typer.Option(
        None,
        "--pattern",
        help=(
            "Glob pattern to match files. "
            f"Default for pipeline: '{_DEFAULT_PIPELINE_PATTERN}'. "
            f"Default for anki: '{_DEFAULT_ANKI_PATTERN}'."
        ),
    ),
    recursive: bool = typer.Option(
        False,
        "--recursive",
        is_flag=True,
        help="Recurse into subdirectories when collecting files.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        is_flag=True,
        help="Print planned file list and derived sources without touching the DB.",
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit",
        help="Maximum number of files to process (applied after sorting).",
    ),
    continue_on_error: bool = typer.Option(
        False,
        "--continue-on-error",
        is_flag=True,
        help="Log parse/import errors and continue; default is to stop on first error.",
    ),
    source_prefix: Optional[str] = typer.Option(
        None,
        "--source-prefix",
        help=(
            "Optional string prepended to each derived label with '__' separator "
            "(e.g. '--source-prefix bulk_2026_03' → 'pipeline:bulk_2026_03__<stem>')."
        ),
    ),
    derive_source: DeriveSource = typer.Option(
        DeriveSource.stem,
        "--derive-source",
        help=(
            "Strategy for deriving the source label from each file path. "
            "'stem': file stem (no extension). "
            "'relative': relative path from --dir with separators replaced by '__'."
        ),
        show_default=True,
    ),
    since: Optional[str] = typer.Option(
        None,
        "--since",
        help=(
            "Only include files whose mtime >= cutoff. "
            "Formats: '7d', '48h', '2026-02-20', '2026-02-20T14:30'. "
            "See --since-tz to control timezone for date/datetime values."
        ),
    ),
    since_tz: str = typer.Option(
        "local",
        "--since-tz",
        help="Timezone for interpreting --since date/datetime values: 'local' or 'utc'.",
        show_default=True,
    ),
) -> None:
    """Bulk-import all matching files from a directory (deterministic, idempotent)."""

    # ── Validate directory ────────────────────────────────────────────────
    if not dir.is_dir():
        typer.echo(f"❌ Directory not found: {dir}", err=True)
        raise typer.Exit(code=1)

    # ── Validate --since-tz ───────────────────────────────────────────────
    if since_tz not in ("local", "utc"):
        typer.echo(f"❌ --since-tz must be 'local' or 'utc', got: {since_tz!r}", err=True)
        raise typer.Exit(code=1)

    # ── Parse --since into a cutoff epoch ────────────────────────────────
    cutoff_epoch: Optional[float] = None
    if since is not None:
        try:
            cutoff_epoch = _parse_since(since, since_tz)
        except ValueError as exc:
            typer.echo(f"❌ {exc}", err=True)
            raise typer.Exit(code=1)
        cutoff_dt_str = datetime.fromtimestamp(cutoff_epoch).strftime("%Y-%m-%d %H:%M:%S")
        typer.echo(f"Cutoff (--since {since!r}): {cutoff_dt_str} local")

    # ── Resolve effective glob pattern ────────────────────────────────────
    effective_pattern = pattern or (
        _DEFAULT_PIPELINE_PATTERN if fmt == ImportFormat.pipeline else _DEFAULT_ANKI_PATTERN
    )

    # ── Collect matching files ────────────────────────────────────────────
    glob_fn = dir.rglob if recursive else dir.glob
    all_files = list(glob_fn(effective_pattern))

    if not all_files:
        typer.echo(
            f"❌ No files matching '{effective_pattern}' found in {dir}.\n"
            f"   Use --pattern to change the pattern, or --recursive to search subdirectories.",
            err=True,
        )
        raise typer.Exit(code=1)

    # ── Sort: mtime DESC, then path ASC as stable tie-break ──────────────
    all_files.sort(key=lambda p: (-p.stat().st_mtime, str(p)))
    typer.echo(f"Found {len(all_files)} file(s) matching '{effective_pattern}' in {dir}.")

    # ── Apply --since mtime filter ────────────────────────────────────────
    if cutoff_epoch is not None:
        before_count = len(all_files)
        all_files = [p for p in all_files if p.stat().st_mtime >= cutoff_epoch]
        excluded = before_count - len(all_files)
        if excluded:
            typer.echo(f"   Excluded {excluded} file(s) with mtime before cutoff.")
        if not all_files:
            typer.echo(
                f"❌ No files remain after applying --since {since!r} "
                f"(cutoff: {cutoff_dt_str}).\n"
                f"   Pattern: '{effective_pattern}'",
                err=True,
            )
            raise typer.Exit(code=1)

    # ── Apply --limit ─────────────────────────────────────────────────────
    candidates = all_files[:limit] if limit is not None else all_files
    if limit is not None and len(all_files) > limit:
        typer.echo(f"   Limiting to first {limit} file(s) (--limit).")

    # ── Dry-run: print plan and exit ──────────────────────────────────────
    if dry_run:
        typer.echo("\nDry-run — no DB changes will be made:")
        for p in candidates:
            raw_label = _derive_label(p, dir, derive_source)
            if source_prefix:
                raw_label = f"{source_prefix}__{raw_label}"
            stored_source = _prefixed_source(raw_label, fmt)
            mtime_str = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            typer.echo(f"  {p}  →  {stored_source}  (mtime: {mtime_str})")
        raise typer.Exit(code=0)

    # ── Connect and ensure schema ─────────────────────────────────────────
    db.parent.mkdir(parents=True, exist_ok=True)
    con = storage.connect(db)

    n_processed         = 0
    skipped_ledger      = 0   # files skipped pre-parse via ledger dedup
    n_failed            = 0
    rows_read_total     = 0
    inserted_total      = 0
    updated_total       = 0
    skipped_r_total     = 0

    try:
        storage.init_db(con)

        for p in candidates:
            raw_label = _derive_label(p, dir, derive_source)
            if source_prefix:
                raw_label = f"{source_prefix}__{raw_label}"
            stored_source = _prefixed_source(raw_label, fmt)

            try:
                result = _import_one_file(con, p, fmt, stored_source)
            except Exception as exc:
                n_failed += 1
                if continue_on_error:
                    typer.echo(f"   ⚠️  {p.name}: {exc} — skipping.")
                    continue
                typer.echo(f"❌ {p.name}: {exc}", err=True)
                raise typer.Exit(code=1)

            if result.already_imported:
                skipped_ledger += 1
                typer.echo(f"   ↩  Already imported: {stored_source}  ({p.name})")
            else:
                n_processed     += 1
                rows_read_total += result.rows_read
                inserted_total  += result.inserted
                updated_total   += result.updated
                skipped_r_total += result.skipped_rows
                typer.echo(
                    f"   ✅ {p.name}  →  {stored_source}"
                    f"  (read={result.rows_read},"
                    f" ins={result.inserted},"
                    f" upd={result.updated},"
                    f" dup={result.skipped_rows})"
                )

        total_in_db = con.execute("SELECT COUNT(*) FROM vocab_items").fetchone()[0]

    finally:
        con.close()

    # ── Summary ───────────────────────────────────────────────────────────
    typer.echo("\n── import-dir summary " + "─" * 40)
    typer.echo(f"   Files matched        : {len(all_files)}")
    typer.echo(f"   Files processed      : {n_processed}")
    typer.echo(f"   Skipped w/o parsing  : {skipped_ledger}  (ledger dedup)")
    if n_failed:
        typer.echo(f"   Import failures      : {n_failed}")
    typer.echo(f"   Rows read (total)    : {rows_read_total}")
    typer.echo(f"   Inserted (total)     : {inserted_total}")
    typer.echo(f"   Updated (total)      : {updated_total}")
    typer.echo(f"   Skipped rows (total) : {skipped_r_total}")
    typer.echo(f"   Total items in DB    : {total_in_db}")


@app.command("practice")
def practice(
    db: Path = typer.Option(
        _DEFAULT_DB,
        "--db",
        help="Path to the SQLite database file.",
        show_default=True,
    ),
    n: int = typer.Option(
        10,
        "--n",
        help="Number of questions per session.",
        show_default=True,
        min=1,
    ),
    source: Optional[str] = typer.Option(
        None,
        "--source",
        help=(
            "Exact source label to filter vocab items "
            "(e.g. 'pipeline:teams_01').  "
            "Mutually exclusive with --source-prefix."
        ),
    ),
    source_prefix: Optional[str] = typer.Option(
        None,
        "--source-prefix",
        help=(
            "Source prefix filter: selects items where source LIKE "
            "'{prefix}%%'.  "
            "Use 'pipeline:' (default when neither flag is given) or "
            "'anki:' to switch buckets.  "
            "Mutually exclusive with --source."
        ),
    ),
    seed: Optional[int] = typer.Option(
        None,
        "--seed",
        help=(
            "Integer seed for reproducible item ordering.  "
            "Affects the random tie-break shuffle applied after the "
            "adaptive (accuracy + recency) ranking.  "
            "Omit for a non-deterministic session."
        ),
    ),
    mode: PracticeMode = typer.Option(
        PracticeMode.mixed,
        "--mode",
        help=(
            "Restrict drill types for this session.  "
            "'mixed' (default): all drill types.  "
            "'translate': English → German (en_to_de) only.  "
            "'articles': article-recall drills only (article / mcq_article).  "
            "'cloze': fill-in-the-blank drills only.  "
            "'mcq': multiple-choice drills only (mcq_en_to_de / mcq_article).  "
            "Non-mixed modes fetch up to n×3 candidates and skip ineligible items."
        ),
        show_default=True,
    ),
) -> None:
    """Run an interactive practice session and log every attempt to the DB."""
    # ── Validate mutually-exclusive filters ───────────────────────────────
    if source and source_prefix:
        typer.echo(
            "❌ --source and --source-prefix are mutually exclusive.", err=True
        )
        raise typer.Exit(code=1)

    # ── Connect ───────────────────────────────────────────────────────────
    if not db.exists():
        typer.echo(f"❌ DB not found: {db}  (run `python cli.py init` first)", err=True)
        raise typer.Exit(code=1)

    con = storage.connect(db)

    try:
        # ── Auto-select source when no filter provided ─────────────────────
        source, source_prefix = _auto_resolve_source(con, source, source_prefix)

        # ── Mode setup ────────────────────────────────────────────────────
        allowed_types = _MODE_ALLOWED_TYPES[mode]
        is_mixed = mode == PracticeMode.mixed

        # Non-mixed modes fetch extra candidates because some items will be
        # skipped when they are ineligible for the requested drill type.
        fetch_n = n if is_mixed else n * 3

        # ── Adaptive item selection via storage helper ─────────────────────
        items = storage.select_practice_items(
            con,
            fetch_n,
            source=source or None,
            source_prefix=source_prefix if source_prefix is not None else None,
            default_pipeline_only=(source is None and source_prefix is None),
            seed=seed,
        )

        if not items:
            typer.echo("⚠️  No vocab items found for the given filter — nothing to practice.")
            raise typer.Exit(code=0)

        mode_note = f"  [mode={mode.value}]" if not is_mixed else ""
        seed_note = f"  (seed={seed})" if seed is not None else ""
        # Mixed: show the actual item count (may be < n when DB is small).
        # Non-mixed: show the target n; actual count is determined during the loop.
        display_n = len(items) if is_mixed else n
        typer.echo(f"\n🎓 Practice session — {display_n} question(s){mode_note}{seed_note}\n")

        # ── Session RNG (seeded for reproducible MCQ option ordering) ────────
        rng = random.Random(seed)   # seed=None gives a non-deterministic RNG

        # ── Question loop ─────────────────────────────────────────────────
        n_correct = 0
        q_num     = 0   # questions asked so far (≤ n)

        for item in items:
            if q_num >= n:
                break

            result = drills.pick_drill_with_pool(item, items, rng, allowed_types)
            if result is None:
                continue   # item ineligible for this mode — try the next candidate

            q_num += 1
            drill_type, prompt, gold_answer, choices, correct_idx = result

            # ── Display prompt ─────────────────────────────────────────────
            typer.echo(f"Q{q_num}/{display_n}  [{drill_type}]")
            if drill_type == "cloze":
                typer.echo(f"  Fill in the blank: {prompt}")
            elif drill_type in ("mcq_en_to_de", "mcq_article"):
                typer.echo(f"  {prompt}")
                for _i, _choice in enumerate(choices):    # choices is not None here
                    typer.echo(f"    {'ABCD'[_i]}) {_choice}")
            else:
                typer.echo(f"  {prompt}")

            t_start = time.perf_counter()
            try:
                user_answer_raw = input("  > ").strip()
            except (EOFError, KeyboardInterrupt):
                typer.echo("\n\nSession interrupted — progress saved.")
                break
            latency_ms = int((time.perf_counter() - t_start) * 1000)

            # ── Grade ──────────────────────────────────────────────────────
            if drill_type in ("mcq_en_to_de", "mcq_article"):
                choice_idx = _parse_mcq_choice(user_answer_raw, len(choices))
                if choice_idx is None:
                    # Unrecognised input — count as wrong
                    is_correct  = False
                    user_answer = user_answer_raw or "(no answer)"
                    error_tags  = "mcq"
                    similarity  = None
                else:
                    is_correct  = (choice_idx == correct_idx)
                    user_answer = f"{'ABCD'[choice_idx]}: {choices[choice_idx]}"
                    if is_correct:
                        error_tags = ""
                    elif drill_type == "mcq_article":
                        # "article" tag lets Step 7 selection pick up the signal
                        error_tags = "mcq article"
                    else:
                        error_tags = "mcq"
                    similarity = None
            else:
                user_answer = user_answer_raw
                is_correct, error_tags, similarity = grade_module.grade(
                    drill_type, gold_answer, user_answer
                )

            # ── Display result ─────────────────────────────────────────────
            if is_correct:
                typer.echo("  ✅ Correct!\n")
                n_correct += 1
            elif drill_type in ("mcq_en_to_de", "mcq_article"):
                correct_str = choices[correct_idx]
                typer.echo(
                    f"  ❌ Correct answer: {'ABCD'[correct_idx]}) {correct_str}\n"
                )
            elif error_tags == "near_miss":
                pct_score = int(similarity * 100) if similarity is not None else 0
                typer.echo(
                    f"  ⚠️  Close ({pct_score}% match) — Expected: {gold_answer}\n"
                )
            else:
                typer.echo(f"  ❌ Expected: {gold_answer}\n")

            # ── Log attempt ───────────────────────────────────────────────
            ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            con.execute(
                "INSERT INTO attempts "
                "(vocab_id, drill_type, prompt, user_answer, is_correct, "
                " error_tags, latency_ms, ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item["id"],
                    drill_type,
                    prompt,
                    user_answer,
                    int(is_correct),
                    error_tags,
                    latency_ms,
                    ts,
                ),
            )
            con.commit()   # persist each attempt immediately

        # ── Session summary ───────────────────────────────────────────────
        answered = q_num
        if not is_mixed and answered < n:
            typer.echo(
                f"⚠️  Only {answered}/{n} questions generated — "
                f"not enough {mode.value!r}-eligible items in the pool.\n"
            )
        pct = int(n_correct / answered * 100) if answered else 0
        total_attempts = con.execute(
            "SELECT COUNT(*) FROM attempts"
        ).fetchone()[0]
        typer.echo(
            f"── Session complete ─────────────────────\n"
            f"   Score          : {n_correct}/{answered} correct ({pct}%)\n"
            f"   Total attempts : {total_attempts} (all sessions)\n"
        )

    finally:
        con.close()


@app.command("stats")
def stats(
    db: Path = typer.Option(
        _DEFAULT_DB,
        "--db",
        help="Path to the SQLite database file.",
        show_default=True,
    ),
    days: int = typer.Option(
        30,
        "--days",
        help="Look-back window in days.",
        show_default=True,
        min=1,
    ),
    source: Optional[str] = typer.Option(
        None,
        "--source",
        help=(
            "Exact source label to filter (e.g. 'pipeline:teams_01').  "
            "Mutually exclusive with --source-prefix."
        ),
    ),
    source_prefix: Optional[str] = typer.Option(
        None,
        "--source-prefix",
        help=(
            "Source prefix filter (e.g. 'pipeline:' or 'anki:').  "
            "Mutually exclusive with --source."
        ),
    ),
) -> None:
    """Show practice health metrics for the last N days."""
    _validate_source_opts(source, source_prefix)

    if not db.exists():
        typer.echo(f"❌ DB not found: {db}  (run `python cli.py init` first)", err=True)
        raise typer.Exit(code=1)

    cutoff = _cutoff_iso(days)

    con = storage.connect(db)
    try:
        source, source_prefix = _auto_resolve_source(con, source, source_prefix)
        pipeline_only = source is None and source_prefix is None
        s = storage.query_stats(
            con,
            cutoff,
            source=source,
            source_prefix=source_prefix,
            default_pipeline_only=pipeline_only,
        )
    finally:
        con.close()

    _print_stats_block(s, days)


@app.command("report")
def report(
    db: Path = typer.Option(
        _DEFAULT_DB,
        "--db",
        help="Path to the SQLite database file.",
        show_default=True,
    ),
    days: int = typer.Option(
        30,
        "--days",
        help="Look-back window in days.",
        show_default=True,
        min=1,
    ),
    n: int = typer.Option(
        20,
        "--n",
        help="Maximum number of worst items to display.",
        show_default=True,
        min=1,
    ),
    source: Optional[str] = typer.Option(
        None,
        "--source",
        help=(
            "Exact source label to filter (e.g. 'pipeline:teams_01').  "
            "Mutually exclusive with --source-prefix."
        ),
    ),
    source_prefix: Optional[str] = typer.Option(
        None,
        "--source-prefix",
        help=(
            "Source prefix filter (e.g. 'pipeline:' or 'anki:').  "
            "Mutually exclusive with --source."
        ),
    ),
) -> None:
    """Show a detailed breakdown of worst-performing items + most-missed all-time."""
    _validate_source_opts(source, source_prefix)

    if not db.exists():
        typer.echo(f"❌ DB not found: {db}  (run `python cli.py init` first)", err=True)
        raise typer.Exit(code=1)

    cutoff = _cutoff_iso(days)

    con = storage.connect(db)
    try:
        source, source_prefix = _auto_resolve_source(con, source, source_prefix)
        pipeline_only = source is None and source_prefix is None
        s          = storage.query_stats(
            con, cutoff, source=source, source_prefix=source_prefix,
            default_pipeline_only=pipeline_only,
        )
        worst      = storage.query_worst_items(
            con, cutoff, n, source=source, source_prefix=source_prefix,
            default_pipeline_only=pipeline_only,
        )
        most_missed = storage.query_most_missed_alltime(con)
    finally:
        con.close()

    _print_stats_block(s, days, header="📋 Practice report")
    _print_worst_items(worst, days, n)
    _print_most_missed(most_missed)


@app.command("focus")
def focus(
    db: Path = typer.Option(
        _DEFAULT_DB,
        "--db",
        help="Path to the SQLite database file.",
        show_default=True,
    ),
    days: int = typer.Option(
        30,
        "--days",
        help="Look-back window in days for performance analysis.",
        show_default=True,
        min=1,
    ),
    source: Optional[str] = typer.Option(
        None,
        "--source",
        help=(
            "Exact source label to analyse (e.g. 'pipeline:teams_01').  "
            "Mutually exclusive with --source-prefix."
        ),
    ),
    source_prefix: Optional[str] = typer.Option(
        None,
        "--source-prefix",
        help=(
            "Source prefix filter (e.g. 'pipeline:').  "
            "Mutually exclusive with --source."
        ),
    ),
    seed: Optional[int] = typer.Option(
        None,
        "--seed",
        help="Integer seed passed through to the practice session.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print chosen mode and metrics without running a practice session.",
        is_flag=True,
    ),
) -> None:
    """Analyse recent performance and run a targeted practice session."""
    _validate_source_opts(source, source_prefix)

    if not db.exists():
        typer.echo(f"❌ DB not found: {db}  (run `python cli.py init` first)", err=True)
        raise typer.Exit(code=1)

    cutoff = _cutoff_iso(days)

    con = storage.connect(db)
    try:
        source, source_prefix = _auto_resolve_source(con, source, source_prefix)
        pipeline_only = source is None and source_prefix is None
        metrics = storage.query_focus_metrics(
            con, cutoff,
            source=source,
            source_prefix=source_prefix,
            default_pipeline_only=pipeline_only,
        )
    finally:
        con.close()

    mode, n, rationale = _choose_focus_mode(metrics)
    # When auto-resolve fell back to a prefix (source is None), build a
    # human-readable display label so _print_focus_summary never shows "None".
    source_display = (
        source if source is not None
        else (f"{source_prefix}*" if source_prefix else "(all sources)")
    )
    _print_focus_summary(metrics, days, source_display, mode, n, rationale)

    if dry_run:
        return

    practice(
        db=db,
        n=n,
        source=source,
        source_prefix=None,
        seed=seed,
        mode=mode,
    )


# ---------------------------------------------------------------------------
# Example-generation helpers (used by generate-examples command)
# ---------------------------------------------------------------------------

def _accusative_np(np: str) -> str:
    """Convert a nominative noun phrase to accusative form.

    Only masculine nouns change: ``der …`` → ``den …``.
    Feminine (``die``) and neuter (``das``) are identical in accusative, so
    they are returned unchanged.  This produces grammatically correct German
    for "Ich sehe …" templates across all three genders.
    """
    if np.lower().startswith("der "):
        return "den " + np[4:]
    return np


def _classify_item(item: dict) -> str:
    """Return a broad word-type tag used by :func:`_generate_example_sentences`.

    Tags (in priority order, explicit notes signals before heuristics):

    ``"noun"``
        ``notes`` contains ``"substantiv"`` (primary, reliable).  Fallback:
        :func:`drills._is_noun` article-prefix heuristic, only after all
        explicit notes signals have been checked (prevents verb phrases like
        ``"Die Liste abhaken"`` from being misclassified as nouns).

    ``"reflexive_verb"``
        ``notes`` contains ``"reflexiv"`` (case-insensitive) **or** ``de``
        starts with ``"sich "`` (case-insensitive).  Checked before
        ``"verb"`` because reflexive verbs also carry the ``"Verb"`` tag.

    ``"adverb"``
        Leading notes token contains ``"adverb"``.  Checked **before**
        ``"verb"`` because ``"adverb"`` is a super-string of ``"verb"``.

    ``"verb"``
        Leading notes token contains ``"verb"`` (catches ``"Verb"``,
        ``"Verbphrase"``, ``"Reflexives Verb"`` etc.).  Also triggered as a
        heuristic when ``de`` starts with a lower-case character and
        contains a space (typical for stored infinitives like
        ``"laufen"`` written without capitalisation).

    ``"adjective"``
        Leading notes token contains ``"adjektiv"`` or ``"adjective"``.

    ``"phrase"``
        ``notes`` contains any of ``"phrase"``, ``"ausdruck"``,
        ``"idiom"`` (case-insensitive).

    ``"other"``
        Fallback when no signal matches.
    """
    notes_lc = (item.get("notes") or "").lower()
    de       = (item.get("de")    or "").strip()
    tok      = drills._notes_type_token(item)  # first word of notes, lower-cased

    # ── Explicit notes signals (checked first, most reliable) ─────────────
    # "Substantiv" is the definitive noun tag from the pipeline importer.
    if "substantiv" in notes_lc:
        return "noun"

    # Reflexive before plain verb (notes may say "Reflexives Verb" or similar)
    if "reflexiv" in notes_lc or de.lower().startswith("sich "):
        return "reflexive_verb"

    # Adverb before verb: "adverb" is a super-string of "verb"
    if "adverb" in tok:
        return "adverb"

    if "verb" in tok:
        return "verb"

    if "adjektiv" in tok or "adjective" in tok:
        return "adjective"

    # Phrase / expression / idiom — catches "Ausdruck", "Idiomatischer Ausdruck"
    if any(w in notes_lc for w in ("phrase", "ausdruck", "idiom")):
        return "phrase"

    # ── Fallback heuristics (less reliable than explicit notes) ────────────
    # Article-prefix heuristic: "Die Liste abhaken" starts with "die" but is
    # actually a verb phrase — only apply this when no notes signal fired above.
    if drills._is_noun(item):
        return "noun"

    # Lowercase-initial + space → probable infinitive / verb phrase
    if de and de[0].islower() and " " in de:
        return "verb"

    return "other"


def _generate_example_sentences(item: dict, max_k: int = 2) -> list[str]:
    """Return up to *max_k* template-based German example sentences for *item*.

    Returns an **empty list** when the item is already sentence-like (passes
    :func:`drills._is_sentence_eligible`) — those items don't need synthetic
    context.  Also returns ``[]`` when ``de`` is blank.

    Template rules per word type
    ----------------------------
    **noun** — uses ``de_mit_artikel`` (nominative); accusative form for
    "Ich sehe …" (``der → den``; feminine/neuter unchanged):

    1. ``"Das ist {de_mit_artikel}."``
    2. ``"Ich sehe {acc}."``

    **reflexive_verb** — strips leading ``"sich "`` and injects ``"mich"``:

    1. ``"Ich möchte mich {rest}."``
    2. ``"Ich werde mich {rest}."``

    **verb** — uses ``de`` (infinitive) directly:

    1. ``"Ich möchte {de}."``
    2. ``"Ich kann {de}."``

    **adjective**:

    1. ``"Das ist {de}."``
    2. ``"Heute bin ich {de}."``

    **adverb** (1 sentence only — further templates risk bad grammar):

    1. ``"Er sagt es {de}."``

    **phrase / expression / idiom**:

    1. ``"Ich versuche, {de}."``
    2. ``"Manchmal muss man einfach {de}."``

    **other / fallback** (1 sentence only):

    1. ``"Das bedeutet: {de}."``
    """
    # ── Sentence gate: skip items that are already sentence-like ──────────
    if drills._is_sentence_eligible(item):
        return []

    de     = (item.get("de")             or "").strip()
    de_mit = (item.get("de_mit_artikel") or de).strip()

    if not de:
        return []

    word_type = _classify_item(item)

    if word_type == "noun":
        acc = _accusative_np(de_mit)
        candidates = [
            f"Das ist {de_mit}.",
            f"Ich sehe {acc}.",
        ]

    elif word_type == "reflexive_verb":
        if de.lower().startswith("sich "):
            rest = de[5:].strip()   # e.g. "verabschieden"
        else:
            rest = de
        candidates = [
            f"Ich möchte mich {rest}.",
            f"Ich werde mich {rest}.",
        ]

    elif word_type == "verb":
        candidates = [
            f"Ich möchte {de}.",
            f"Ich kann {de}.",
        ]

    elif word_type == "adjective":
        candidates = [
            f"Das ist {de}.",
            f"Heute bin ich {de}.",
        ]

    elif word_type == "adverb":
        candidates = [f"Er sagt es {de}."]    # one template only for adverbs

    elif word_type == "phrase":
        candidates = [
            f"Ich versuche, {de}.",
            f"Manchmal muss man einfach {de}.",
        ]

    else:   # "other" / unknown
        candidates = [f"Das bedeutet: {de}."]

    return candidates[:max_k]


@app.command("generate-examples")
def generate_examples(
    db: Path = typer.Option(
        _DEFAULT_DB,
        "--db",
        help="Path to the SQLite database file.",
        show_default=True,
    ),
    max_per_item: int = typer.Option(
        2,
        "--max-per-item",
        help="Maximum number of example sentences to generate per vocab item.",
        show_default=True,
        min=1,
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit",
        help="Process at most this many vocab items (useful for testing).",
        min=1,
    ),
    source: Optional[str] = typer.Option(
        None,
        "--source",
        help=(
            "Exact source label to filter (e.g. 'pipeline:teams_01').  "
            "Mutually exclusive with --source-prefix."
        ),
    ),
    source_prefix: Optional[str] = typer.Option(
        None,
        "--source-prefix",
        help=(
            "Source prefix filter (e.g. 'pipeline:').  "
            "Mutually exclusive with --source."
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print what would be generated without writing to the DB.",
    ),
) -> None:
    """Generate template-based example sentences for vocab items that lack them.

    Only items that are *not* already sentence-like (i.e. they would not
    pass the cloze eligibility gate) are considered.  For each eligible item
    up to ``--max-per-item`` sentences are generated from language-specific
    templates (nouns, verbs, adjectives, adverbs, phrases).

    Re-running is safe: sentences already stored in ``examples`` are skipped
    so no duplicates are created.
    """
    _validate_source_opts(source, source_prefix)

    if not db.exists():
        typer.echo(f"❌ DB not found: {db}  (run `python cli.py init` first)", err=True)
        raise typer.Exit(code=1)

    con = storage.connect(db)
    try:
        source, source_prefix = _auto_resolve_source(con, source, source_prefix)
        pipeline_only = source is None and source_prefix is None

        items = storage.fetch_vocab_items_all(
            con,
            source=source, source_prefix=source_prefix,
            default_pipeline_only=pipeline_only,
            limit=limit,
        )
    except Exception:
        con.close()
        raise

    if dry_run:
        typer.echo(
            f"\n🔍 Dry-run (no DB writes)"
            f"  — up to {max_per_item} example(s) per item\n"
            f"{'─' * 60}"
        )

    n_sentence_items = 0  # skipped — already sentence-like
    n_empty_items    = 0  # skipped — no de content
    n_processed      = 0  # items that had at least one template
    n_inserted       = 0  # sentences actually written (real run)
    n_already_exist  = 0  # sentences skipped because already in DB

    try:
        for item in items:
            sentences = _generate_example_sentences(item, max_per_item)

            if not sentences:
                # Distinguish "already a sentence" from "no content"
                de = (item.get("de") or "").strip()
                if de and drills._is_sentence_eligible(item):
                    n_sentence_items += 1
                else:
                    n_empty_items += 1
                continue

            n_processed += 1

            # Fetch already-stored sentences to detect duplicates
            existing: set[str] = storage.fetch_existing_example_sentences(
                con, item["id"]
            )

            if dry_run:
                de_display = _trunc(item.get("de") or "", 35)
                wt         = _classify_item(item)
                typer.echo(f"[ID {item['id']:>3} | {wt:<14}]  {de_display}")
                for sent in sentences:
                    marker = "  (already stored)" if sent in existing else ""
                    typer.echo(f"    → {sent}{marker}")
            else:
                for sent in sentences:
                    if sent in existing:
                        n_already_exist += 1
                        continue
                    storage.insert_example(
                        con,
                        vocab_id=item["id"],
                        de_sentence=sent,
                        difficulty=2,
                        style_tag="template",
                    )
                    existing.add(sent)   # prevent in-loop self-duplicates
                    n_inserted += 1

        if not dry_run:
            con.commit()

    finally:
        con.close()

    # ── Summary ───────────────────────────────────────────────────────────
    if dry_run:
        typer.echo(f"{'─' * 60}")
        typer.echo(
            f"\n📋 Dry-run summary\n"
            f"   Items checked          : {len(items)}\n"
            f"   Items with templates   : {n_processed}\n"
            f"   Sentence-like skipped  : {n_sentence_items}\n"
            f"   Empty / skipped        : {n_empty_items}\n"
        )
    else:
        typer.echo(
            f"\n✅ generate-examples complete\n"
            f"   Items checked          : {len(items)}\n"
            f"   Items with templates   : {n_processed}\n"
            f"   Sentences inserted     : {n_inserted}\n"
            f"   Already existed        : {n_already_exist}\n"
            f"   Sentence-like skipped  : {n_sentence_items}\n"
        )


def _notes_short(notes: Optional[str], max_len: int = 60) -> str:
    """Return a truncated version of *notes* for Anki card backs.

    Keeps up to *max_len* characters, appending '…' when cut.  Returns an
    empty string if *notes* is ``None`` or blank.
    """
    if not notes:
        return ""
    return notes if len(notes) <= max_len else notes[: max_len - 1] + "…"


@app.command("export-pack")
def export_pack(
    db: Path = typer.Option(
        _DEFAULT_DB,
        "--db",
        help="Path to the SQLite database file.",
        show_default=True,
    ),
    days: int = typer.Option(
        30,
        "--days",
        help="Look-back window in days for the worst-items query.",
        show_default=True,
        min=1,
    ),
    worst_n: int = typer.Option(
        30,
        "--worst-n",
        help="Number of worst-performing items (window) to include.",
        show_default=True,
        min=0,
    ),
    missed_n: int = typer.Option(
        20,
        "--missed-n",
        help="Number of most-missed items (all-time) to include.",
        show_default=True,
        min=0,
    ),
    min_attempts: int = typer.Option(
        3,
        "--min-attempts",
        help=(
            "Minimum window attempts required for an item to appear in the "
            "worst-items list.  Use 0 to include never-practised items."
        ),
        show_default=True,
        min=0,
    ),
    source: Optional[str] = typer.Option(
        None,
        "--source",
        help=(
            "Exact source label to filter (e.g. 'pipeline:teams_01').  "
            "Mutually exclusive with --source-prefix."
        ),
    ),
    source_prefix: Optional[str] = typer.Option(
        None,
        "--source-prefix",
        help=(
            "Source prefix filter (e.g. 'pipeline:').  "
            "Mutually exclusive with --source."
        ),
    ),
    alltime_scope: AllTimeScope = typer.Option(
        AllTimeScope.filtered,
        "--alltime-scope",
        help=(
            "Scope for the most-missed all-time query.  "
            "'filtered' (default): apply the same source filter as worst-items.  "
            "'global': no source filter — truly all-time across every source."
        ),
        show_default=True,
    ),
    out_dir: Path = typer.Option(
        Path("output"),
        "--out-dir",
        help="Directory to write the exported files into.",
        show_default=True,
    ),
) -> None:
    """Export worst + most-missed items as a timestamped Anki TSV and full CSV.

    Two files are written to ``--out-dir``:

    \b
    1. ``study_pack_YYYY-MM-DD_HH-MM.tsv``  — two-column Anki import file
       Front: German word (de_mit_artikel or de)
       Back : English meaning — brief notes hint
    2. ``study_pack_YYYY-MM-DD_HH-MM.csv``  — full details with all metric
       columns (id, de, de_mit_artikel, en, af, notes, source, pack_source,
       window accuracy/attempts/near-misses, all-time miss_count/accuracy).

    Pack composition (union by vocab_id, no duplicates):
      • Worst N items  — lowest window accuracy, ≥ ``--min-attempts`` attempts
      • Most-missed N  — highest all-time miss count, ≥ ``--min-attempts`` total
    """
    _validate_source_opts(source, source_prefix)

    if not db.exists():
        typer.echo(f"❌ DB not found: {db}  (run `python cli.py init` first)", err=True)
        raise typer.Exit(code=1)

    cutoff = _cutoff_iso(days)

    con = storage.connect(db)
    try:
        source, source_prefix = _auto_resolve_source(con, source, source_prefix)
        pipeline_only = source is None and source_prefix is None

        # ── Worst items: window, source-filtered ──────────────────────────
        worst = storage.query_worst_items(
            con, cutoff, worst_n,
            source=source, source_prefix=source_prefix,
            default_pipeline_only=pipeline_only,
            min_attempts=min_attempts,
        )

        # ── Most-missed: all-time, scope-dependent ────────────────────────
        if alltime_scope == AllTimeScope.global_:
            missed = storage.query_most_missed_alltime(
                con, top_n=missed_n,
                min_attempts=min_attempts,
                # no source filter — global scope
            )
        else:   # filtered
            missed = storage.query_most_missed_alltime(
                con, top_n=missed_n,
                min_attempts=min_attempts,
                source=source, source_prefix=source_prefix,
                default_pipeline_only=pipeline_only,
            )

        # ── Union by vocab_id ─────────────────────────────────────────────
        worst_ids  = {row["id"] for row in worst}
        missed_ids = {row["id"] for row in missed}
        all_ids    = list(worst_ids | missed_ids)

        if not all_ids:
            typer.echo(
                "⚠️  No items found matching the given filters and thresholds — "
                "nothing to export.\n"
                "   Tip: lower --min-attempts or widen the source filter.",
            )
            raise typer.Exit(code=0)

        # ── Fetch full vocab fields ───────────────────────────────────────
        vocab_rows = storage.fetch_vocab_by_ids(con, all_ids)

    finally:
        con.close()

    # ── Build lookup tables ───────────────────────────────────────────────
    worst_by_id  = {r["id"]: r for r in worst}
    missed_by_id = {r["id"]: r for r in missed}
    vocab_by_id  = {r["id"]: r for r in vocab_rows}

    # ── Stable output order: worst (in rank order) then missed-only ───────
    worst_ordered = [r["id"] for r in worst]
    missed_only   = [r["id"] for r in missed if r["id"] not in worst_ids]
    ordered_ids   = worst_ordered + missed_only

    def _pack_membership(vid: int) -> str:
        in_w = vid in worst_ids
        in_m = vid in missed_ids
        if in_w and in_m:
            return "both"
        return "worst" if in_w else "missed"

    # ── Prepare output directory + timestamped filenames ─────────────────
    ts_str   = datetime.now().strftime("%Y-%m-%d_%H-%M")
    out_dir.mkdir(parents=True, exist_ok=True)
    tsv_path = out_dir / f"study_pack_{ts_str}.tsv"
    csv_path = out_dir / f"study_pack_{ts_str}.csv"

    # ── Write Anki TSV (2-col, no header — Anki import format) ───────────
    tsv_count = 0
    with tsv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        for vid in ordered_ids:
            v = vocab_by_id.get(vid)
            if not v:
                continue
            front = (v.get("de_mit_artikel") or v.get("de") or "").strip()
            en    = (v.get("en") or "").strip()
            ns    = _notes_short(v.get("notes"))
            back  = f"{en} — {ns}" if ns else en
            writer.writerow([front, back])
            tsv_count += 1

    # ── Write full CSV (with all metric columns) ──────────────────────────
    _CSV_FIELDS = [
        "id", "de", "de_mit_artikel", "en", "af", "notes", "source",
        "pack_source",
        # window metrics (from worst_items; blank for missed-only items)
        "acc_window", "attempts_window", "near_miss_window", "last_seen",
        # all-time metrics (from most_missed; blank for worst-only items)
        "miss_count", "total_attempts", "acc_alltime",
    ]
    csv_count = 0
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for vid in ordered_ids:
            v = vocab_by_id.get(vid)
            if not v:
                continue
            w = worst_by_id.get(vid, {})
            m = missed_by_id.get(vid, {})
            writer.writerow({
                "id":               vid,
                "de":               v.get("de") or "",
                "de_mit_artikel":   v.get("de_mit_artikel") or "",
                "en":               v.get("en") or "",
                "af":               v.get("af") or "",
                "notes":            v.get("notes") or "",
                "source":           v.get("source") or "",
                "pack_source":      _pack_membership(vid),
                # window metrics — present only for items in worst list
                "acc_window":       f"{w['acc_window']:.4f}" if "acc_window" in w else "",
                "attempts_window":  w.get("attempts_window", ""),
                "near_miss_window": w.get("near_miss_window", ""),
                "last_seen":        w.get("last_seen") or "",
                # all-time metrics — present only for items in missed list
                "miss_count":       m.get("miss_count", ""),
                "total_attempts":   m.get("total_attempts", ""),
                "acc_alltime":      f"{m['acc_alltime']:.4f}" if "acc_alltime" in m else "",
            })
            csv_count += 1

    # ── Summary ───────────────────────────────────────────────────────────
    both_count = len(worst_ids & missed_ids)
    source_display = (
        source if source is not None
        else (f"{source_prefix}*" if source_prefix else "(all sources)")
    )
    typer.echo(
        f"\n📦 Study pack exported\n"
        f"   Source filter : {source_display}\n"
        f"   Window        : last {days} days, ≥{min_attempts} attempts\n"
        f"   Alltime scope : {alltime_scope.value}\n"
        f"   {'─' * 38}\n"
        f"   Worst items   : {len(worst_ids)}\n"
        f"   Most-missed   : {len(missed_ids)}\n"
        f"   In both       : {both_count}\n"
        f"   Total exported: {csv_count}\n"
        f"\n"
        f"   Anki TSV  → {tsv_path}\n"
        f"   Full CSV  → {csv_path}\n"
    )


@app.command("daily")
def daily(
    db: Path = typer.Option(
        _DEFAULT_DB,
        "--db",
        help="Path to the SQLite database file.",
        show_default=True,
    ),
    seed: Optional[int] = typer.Option(
        None,
        "--seed",
        help="Integer seed for reproducible item ordering.",
    ),
) -> None:
    """15-question mixed practice session using the latest pipeline source."""
    practice(db=db, n=15, source=None, source_prefix=None, seed=seed, mode=PracticeMode.mixed)


@app.command("drill-articles")
def drill_articles(
    db: Path = typer.Option(
        _DEFAULT_DB,
        "--db",
        help="Path to the SQLite database file.",
        show_default=True,
    ),
    seed: Optional[int] = typer.Option(
        None,
        "--seed",
        help="Integer seed for reproducible item ordering.",
    ),
) -> None:
    """15-question article-recall drill using the latest pipeline source."""
    practice(db=db, n=15, source=None, source_prefix=None, seed=seed, mode=PracticeMode.articles)


@app.command("drill-cloze")
def drill_cloze(
    db: Path = typer.Option(
        _DEFAULT_DB,
        "--db",
        help="Path to the SQLite database file.",
        show_default=True,
    ),
    seed: Optional[int] = typer.Option(
        None,
        "--seed",
        help="Integer seed for reproducible item ordering.",
    ),
) -> None:
    """10-question cloze (fill-in-the-blank) drill using the latest pipeline source."""
    practice(db=db, n=10, source=None, source_prefix=None, seed=seed, mode=PracticeMode.cloze)


@app.command("drill-mcq")
def drill_mcq(
    db: Path = typer.Option(
        _DEFAULT_DB,
        "--db",
        help="Path to the SQLite database file.",
        show_default=True,
    ),
    seed: Optional[int] = typer.Option(
        None,
        "--seed",
        help="Integer seed for reproducible item ordering.",
    ),
) -> None:
    """10-question multiple-choice drill using the latest pipeline source."""
    practice(db=db, n=10, source=None, source_prefix=None, seed=seed, mode=PracticeMode.mcq)


@app.command("weekly-report")
def weekly_report(
    db: Path = typer.Option(
        _DEFAULT_DB,
        "--db",
        help="Path to the SQLite database file.",
        show_default=True,
    ),
) -> None:
    """7-day practice report with top 20 worst items using the latest pipeline source."""
    report(db=db, days=7, n=20, source=None, source_prefix=None)


if __name__ == "__main__":
    app()
