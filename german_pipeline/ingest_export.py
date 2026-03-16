"""
german_pipeline.ingest_export
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Read a TSV/CSV/XLSX vocabulary export and upsert rows into ``vocab_items``.

Supported input formats (selected explicitly with the ``fmt`` argument)
-----------------------------------------------------------------------
``"pipeline"``
    Header row required.  Supported file types: .tsv, .csv, .xlsx.
    Expected columns (case-sensitive, with alias normalisation applied first):
        Deutsch | Deutsch mit Artikel | Englisch | Afrikaans |
        Wortart / Genus / Hinweise
    At minimum ``Deutsch`` and ``Englisch`` must be present.
    Extra columns (e.g. Front, Back) are silently ignored.
    Raises ``ValueError`` if the required headers are absent.

``"anki"``
    Headerless TSV/CSV, exactly 2 columns per row.
    Column 1 → de / de_mit_artikel (Front).
    Column 2 → en verbatim (Back) — no em-dash parsing is attempted.
    Not supported for .xlsx files.
    Raises ``ValueError`` if any non-empty row does not have exactly 2 columns.

Header alias normalisation (pipeline mode only)
-----------------------------------------------
Before checking required headers, each raw header is stripped of whitespace
and then matched case-insensitively against a small alias table.  Recognised
aliases are remapped to their canonical name; all other headers are kept as-is
(with only whitespace stripped).  Aliases handled:

    "Wortart/Genus/Hinweise"    → "Wortart / Genus / Hinweise"
    "Deutsch mit artikel"       → "Deutsch mit Artikel"
    "English"                   → "Englisch"
    "Afrikaans "  (any casing)  → "Afrikaans"
"""

from __future__ import annotations

import csv
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Column mapping for the pipeline (rich) format
# ---------------------------------------------------------------------------

_RICH_COLUMN_MAP: dict[str, str] = {
    "Deutsch":                    "de",
    "Deutsch mit Artikel":        "de_mit_artikel",
    "Englisch":                   "en",
    "Afrikaans":                  "af",
    "Wortart / Genus / Hinweise": "notes",
}

# Minimum headers that must be present for pipeline mode to proceed
_REQUIRED_HEADERS: frozenset[str] = frozenset({"Deutsch", "Englisch"})

# Alias map: casefolded-stripped form → canonical header name.
# Applied only for the listed keys; unknown headers are kept as-is.
_HEADER_ALIASES: dict[str, str] = {
    "wortart/genus/hinweise":  "Wortart / Genus / Hinweise",
    "deutsch mit artikel":     "Deutsch mit Artikel",
    "english":                 "Englisch",
    "afrikaans":               "Afrikaans",
}


# ---------------------------------------------------------------------------
# Conservative casing-glitch repair (pipeline mode only)
# ---------------------------------------------------------------------------

# Matches a run of alphabetical characters including German umlauts.
# Punctuation and digits are left in-place, which means the positional
# word index only increments on actual word tokens — not on "–" or ",".
_WORD_RE: re.Pattern[str] = re.compile(r"[A-Za-zÄÖÜäöüß]+")


def _is_glitchy_word(word: str) -> bool:
    """Return ``True`` for words with clearly erroneous mixed casing.

    A word is flagged **only** when it starts with a lowercase letter but
    contains at least one uppercase letter inside (e.g. ``"lIste"``,
    ``"abHaken"``).  Words that start with an uppercase letter and have
    mixed casing in the tail are left alone — they may be legitimate
    abbreviations (``"GmbH"``, ``"iPhone"``) or standard German nouns
    (``"Liste"``, ``"Tennisplatz"``), which this function must never damage.
    """
    if len(word) < 2:
        return False
    # Need both cases present
    if not any(c.isupper() for c in word):
        return False
    if not any(c.islower() for c in word):
        return False
    # Only flag if the word *starts* with a lowercase letter
    return word[0].islower()


def _fix_glitchy_case(text: str) -> str:
    """Apply a conservative casing fix to a German phrase or sentence.

    Scans each alphabetical token in *text* in order.  The **first** token
    is never modified (sentence-initial capitalisation is intentional).
    Any subsequent token that satisfies :func:`_is_glitchy_word` is
    title-cased (first character upper, remainder lower), matching the
    standard German noun convention.  All other tokens and non-alphabetical
    characters are returned unchanged.

    If *text* contains no glitchy words the original string is returned
    unchanged (no copy is made).

    Examples::

        >>> _fix_glitchy_case("Die lIste abhaken")
        'Die Liste abhaken'
        >>> _fix_glitchy_case("der Tennisplatz")   # already correct
        'der Tennisplatz'
        >>> _fix_glitchy_case("GmbH")              # first-word guard
        'GmbH'
    """
    word_idx = 0

    def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
        nonlocal word_idx
        current = word_idx
        word_idx += 1
        word = m.group()
        # First token is never touched regardless of casing
        if current == 0:
            return word
        if _is_glitchy_word(word):
            return word[0].upper() + word[1:].lower()
        return word

    return _WORD_RE.sub(_replace, text)


def _apply_pipeline_cleanup(rows: list[dict]) -> list[dict]:
    """Apply conservative quality fixes to pipeline-imported rows in-place.

    Currently fixes obvious casing glitches (e.g. ``"lIste"`` →
    ``"Liste"``) in the ``de`` and ``de_mit_artikel`` fields only.
    Anki-imported rows are never passed through this function.
    """
    for row in rows:
        if row.get("de"):
            row["de"] = _fix_glitchy_case(row["de"])
        if row.get("de_mit_artikel"):
            row["de_mit_artikel"] = _fix_glitchy_case(row["de_mit_artikel"])
    return rows


# ---------------------------------------------------------------------------
# Normalisation helpers (used only for deduplication keys)
# ---------------------------------------------------------------------------

def normalize_key(s: str) -> str:
    """Strip whitespace and casefold *s* for use as a deduplication key."""
    return s.strip().casefold()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_match_key(row: dict) -> str:
    """Stable match key: normalize(de_mit_artikel or de) + NUL + normalize(en)."""
    de_part = row.get("de_mit_artikel") or row.get("de") or ""
    en_part = row.get("en") or ""
    return normalize_key(de_part) + "\x00" + normalize_key(en_part)


def _normalize_header(raw: str) -> str:
    """Strip *raw* and apply the alias map if it matches; otherwise return stripped."""
    stripped = raw.strip()
    return _HEADER_ALIASES.get(stripped.casefold(), stripped)


def _check_required_headers(normalized: list[str]) -> None:
    """Raise ``ValueError`` if any required pipeline headers are absent.

    *normalized* is the list of headers after ``_normalize_header`` has been
    applied.  The error message includes the detected and missing header names
    so the user can diagnose the problem immediately.
    """
    missing = _REQUIRED_HEADERS - set(normalized)
    if missing:
        displayed = normalized if normalized else ["(no columns detected)"]
        raise ValueError(
            f"pipeline format requires headers {sorted(_REQUIRED_HEADERS)!r} "
            f"but they were not found.\n"
            f"  Detected : {displayed!r}\n"
            f"  Missing  : {sorted(missing)!r}\n"
            f"Hint: use --format anki for headerless two-column files."
        )


# ---------------------------------------------------------------------------
# Format-specific readers (private)
# ---------------------------------------------------------------------------

def _read_pipeline_csv(path: Path, delimiter: str) -> list[dict]:
    """Read a headered TSV/CSV pipeline export.

    Normalises header aliases, validates required headers, then maps each
    row to internal field names.  Extra columns are silently ignored.
    """
    with path.open(encoding="utf-8", newline="") as fh:
        # ── Read and normalise the header row ────────────────────────────
        raw_reader = csv.reader(fh, delimiter=delimiter)
        raw_headers = next(raw_reader, None)
        if raw_headers is None:
            raise ValueError("File is empty (no rows found).")

        normalized = [_normalize_header(h) for h in raw_headers]
        _check_required_headers(normalized)

        # ── Re-read data rows via DictReader with normalised fieldnames ──
        # Seeking back and using explicit fieldnames avoids re-reading the
        # header line as a data row while preserving DictReader convenience.
        fh.seek(0)
        dict_reader = csv.DictReader(fh, delimiter=delimiter,
                                     fieldnames=normalized)
        next(dict_reader)  # discard the original header row

        rows: list[dict] = []
        for raw in dict_reader:
            row = {
                dst: (raw.get(src) or "").strip()
                for src, dst in _RICH_COLUMN_MAP.items()
            }
            if not any(row.values()):
                continue
            rows.append(row)

    return rows


def _read_pipeline_xlsx(path: Path) -> list[dict]:
    """Read a headered XLSX pipeline export using openpyxl.

    Uses the first worksheet, ``data_only=True`` (cached values, not
    formulae).  Normalises header aliases, validates required headers,
    then maps each row to internal field names.  Extra columns are
    silently ignored.  Fully empty rows are skipped.
    """
    import openpyxl  # stdlib-adjacent; already in environment.yml

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.active
        row_iter = ws.iter_rows(values_only=True)

        # ── Read and normalise the header row ────────────────────────────
        raw_headers_row = next(row_iter, None)
        if raw_headers_row is None:
            raise ValueError("XLSX file is empty (no rows found).")

        normalized = [
            _normalize_header(str(h) if h is not None else "")
            for h in raw_headers_row
        ]
        _check_required_headers(normalized)

        # ── Build column-index map: internal_field → column position ─────
        col_idx: dict[str, int] = {}
        for i, h in enumerate(normalized):
            if h in _RICH_COLUMN_MAP:
                col_idx[_RICH_COLUMN_MAP[h]] = i

        # ── Read data rows ───────────────────────────────────────────────
        rows: list[dict] = []
        for data_row in row_iter:
            row: dict[str, str] = {}
            for dst, idx in col_idx.items():
                val = data_row[idx] if idx < len(data_row) else None
                row[dst] = str(val).strip() if val is not None else ""
            # Ensure all internal fields are present (fill missing with "")
            for dst in _RICH_COLUMN_MAP.values():
                row.setdefault(dst, "")
            if not any(row.values()):
                continue
            rows.append(row)

    finally:
        wb.close()

    return rows


def _read_pipeline(path: Path, delimiter: str) -> list[dict]:
    """Dispatch to the correct pipeline reader and apply cleanup."""
    if path.suffix.lower() == ".xlsx":
        rows = _read_pipeline_xlsx(path)
    else:
        rows = _read_pipeline_csv(path, delimiter)
    return _apply_pipeline_cleanup(rows)


def _read_anki(path: Path, delimiter: str) -> list[dict]:
    """Read a headerless Anki TSV/CSV with exactly 2 columns per row.

    Column 1 → ``de`` / ``de_mit_artikel`` (Front).
    Column 2 → ``en`` verbatim (Back), no em-dash parsing.

    Raises ``ValueError`` on the first non-empty row that does not have
    exactly 2 columns.
    """
    rows: list[dict] = []

    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh, delimiter=delimiter)

        for row_num, fields in enumerate(reader, start=1):
            # Skip completely blank rows
            if not any(f.strip() for f in fields):
                continue

            if len(fields) != 2:
                raise ValueError(
                    f"anki format expects exactly 2 columns per row, "
                    f"but row {row_num} has {len(fields)}.\n"
                    f"  Row content: {fields!r}\n"
                    f"Hint: use --format pipeline for files with a header row."
                )

            front = fields[0].strip()
            back  = fields[1].strip()

            if not front and not back:
                continue

            rows.append({
                "de":             front,
                "de_mit_artikel": front,
                "en":             back,   # stored verbatim
                "af":             "",
                "notes":          "",
            })

    return rows


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read_table(path: str | Path, fmt: str = "pipeline") -> list[dict]:
    """Read *path* and return a list of normalised vocab dicts.

    Parameters
    ----------
    path:
        Path to the file.  Supported extensions:

        - ``.xlsx`` — pipeline mode only
        - ``.tsv``  — tab delimiter; either mode
        - ``.csv``  — comma delimiter; either mode

    fmt:
        ``"pipeline"`` (default) or ``"anki"``.  See module docstring.

    Raises
    ------
    ValueError
        pipeline mode: required headers absent, or unsupported combination.
        anki mode: non-empty row has column count ≠ 2, or .xlsx supplied.
        Either mode: *fmt* is not a recognised value.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    delimiter = "\t" if suffix == ".tsv" else ","

    if fmt == "pipeline":
        return _read_pipeline(path, delimiter)

    elif fmt == "anki":
        if suffix == ".xlsx":
            raise ValueError(
                "anki format does not support .xlsx files.\n"
                "Hint: use --format pipeline for XLSX imports."
            )
        return _read_anki(path, delimiter)

    else:
        raise ValueError(
            f"Unknown format {fmt!r}.  Expected 'pipeline' or 'anki'."
        )


def upsert_vocab_items(
    con: sqlite3.Connection,
    rows: list[dict],
    source: str,
) -> tuple[int, int]:
    """Upsert *rows* into ``vocab_items`` using a normalised match key.

    Match key: ``normalize(de_mit_artikel or de)`` + ``\\x00`` +
               ``normalize(en)``

    * **INSERT**: sets ``created_at`` (UTC ISO-8601) and ``source``.
    * **UPDATE**: refreshes ``de``, ``de_mit_artikel``, ``en``, ``af``,
      ``notes``.  ``created_at`` is never overwritten.  ``source`` is only
      written when the stored value is empty/NULL.
    * Rows that are already identical in the DB are skipped (no-op), so
      re-running with the same file produces 0 inserts and 0 updates.

    Returns ``(insert_count, update_count)``.
    """
    # ── Load existing rows into an in-memory index ────────────────────────
    existing: dict[str, dict] = {}
    for db_row in con.execute(
        "SELECT id, de, de_mit_artikel, en, af, notes, created_at, source "
        "FROM vocab_items"
    ).fetchall():
        id_, de, de_mit_artikel, en, af, notes, created_at, db_source = db_row
        key = (
            normalize_key(de_mit_artikel or de or "")
            + "\x00"
            + normalize_key(en or "")
        )
        existing[key] = {
            "id":             id_,
            "de":             de,
            "de_mit_artikel": de_mit_artikel,
            "en":             en,
            "af":             af,
            "notes":          notes,
            "created_at":     created_at,
            "source":         db_source,
        }

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    insert_count = 0
    update_count = 0

    for row in rows:
        key = _make_match_key(row)

        if key in existing:
            ex = existing[key]

            new_de             = row.get("de") or ""
            new_de_mit_artikel = row.get("de_mit_artikel") or ""
            new_en             = row.get("en") or ""
            new_af             = row.get("af") or ""
            new_notes          = row.get("notes") or ""

            # Preserve existing source if it is already set
            new_source = ex["source"] if ex["source"] else source

            # Skip entirely if nothing would change
            if (
                ex["de"]             == new_de
                and ex["de_mit_artikel"] == new_de_mit_artikel
                and ex["en"]             == new_en
                and ex["af"]             == new_af
                and ex["notes"]          == new_notes
                and ex["source"]         == new_source
            ):
                continue

            con.execute(
                "UPDATE vocab_items "
                "SET de=?, de_mit_artikel=?, en=?, af=?, notes=?, source=? "
                "WHERE id=?",
                (new_de, new_de_mit_artikel, new_en, new_af, new_notes,
                 new_source, ex["id"]),
            )
            update_count += 1

        else:
            con.execute(
                "INSERT INTO vocab_items "
                "(de, de_mit_artikel, en, af, notes, created_at, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("de") or "",
                    row.get("de_mit_artikel") or "",
                    row.get("en") or "",
                    row.get("af") or "",
                    row.get("notes") or "",
                    now,
                    source,
                ),
            )
            existing[key] = {
                "id":             None,
                "de":             row.get("de") or "",
                "de_mit_artikel": row.get("de_mit_artikel") or "",
                "en":             row.get("en") or "",
                "af":             row.get("af") or "",
                "notes":          row.get("notes") or "",
                "created_at":     now,
                "source":         source,
            }
            insert_count += 1

    con.commit()
    return insert_count, update_count
