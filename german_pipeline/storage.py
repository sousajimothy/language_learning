"""
german_pipeline.storage
~~~~~~~~~~~~~~~~~~~~~~~
SQLite connection + schema helpers for the practice pipeline.

All functions accept a plain ``sqlite3.Connection``; callers own the
connection lifecycle (open / close / context-manage as needed).

Adaptive item selection
-----------------------
``select_practice_items`` ranks candidates by a composite *priority score*
computed over a 30-day rolling window of attempts::

    base              = 1.0 - COALESCE(acc_window, 0.0)
    near_miss_rate    = near_miss_window / attempts_window
    article_err_rate  = article_wrong_window / article_attempts_window  (nouns only)
    priority          = base
                      + near_miss_rate    * _NEAR_MISS_BOOST
                      + article_err_rate  * _ARTICLE_BOOST

Key design decisions:

* **Near-miss denominator** — ``attempts_window`` (all drill types): a near-miss
  is meaningful relative to *all* recent attempts on the item.
* **Article-error denominator** — ``article_attempts_window`` (article drills
  only): using total attempts would dilute the signal when most attempts are
  ``en_to_de`` drills.  ``article_wrong`` only counts attempts where
  ``drill_type='article'`` AND ``is_correct=0`` AND ``error_tags LIKE
  '%article%'``, so retried-correct article drills do not inflate the rate.
* **Noun gate** — the article boost is only applied when the item is classified
  as a noun (``notes LIKE '%Substantiv%'`` or ``de_mit_artikel`` begins with
  a definite article).  Non-noun items have ``article_attempts_window = 0`` in
  practice (``pick_drill`` never generates article drills for them), so the gate
  is belt-and-suspenders against any historical data anomalies.

Selection order:

1. **Highest priority** — weakest items with error-pattern signals surface first.
   Unseen items score ``priority = 1.0`` (maximum base, zero boosts) and share
   the top bucket with always-wrong items.
2. **Oldest ``last_seen``** — ``NULL`` sorts first (never-seen beats stale).
3. **Python shuffle with optional seed** — randomises remaining ties.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# DDL — one constant per table keeps init_db() easy to extend
# ---------------------------------------------------------------------------

_DDL_VOCAB_ITEMS = """
CREATE TABLE IF NOT EXISTS vocab_items (
    id              INTEGER PRIMARY KEY,
    de              TEXT,
    de_mit_artikel  TEXT,
    en              TEXT,
    af              TEXT,
    notes           TEXT,
    word_type       TEXT,
    lemma           TEXT,
    created_at      TEXT,
    source          TEXT
);
"""

_DDL_EXAMPLES = """
CREATE TABLE IF NOT EXISTS examples (
    id          INTEGER PRIMARY KEY,
    vocab_id    INTEGER NOT NULL REFERENCES vocab_items(id),
    de_sentence TEXT,
    en_sentence TEXT,
    af_sentence TEXT,
    difficulty  INTEGER,
    style_tag   TEXT
);
"""

_DDL_ATTEMPTS = """
CREATE TABLE IF NOT EXISTS attempts (
    id          INTEGER PRIMARY KEY,
    vocab_id    INTEGER NOT NULL REFERENCES vocab_items(id),
    drill_type  TEXT    NOT NULL,
    prompt      TEXT    NOT NULL,
    user_answer TEXT,
    is_correct  INTEGER NOT NULL,
    error_tags  TEXT,
    latency_ms  INTEGER,
    ts          TEXT    NOT NULL
);
"""

_DDL_IMPORTS = """
CREATE TABLE IF NOT EXISTS imports (
    id          INTEGER PRIMARY KEY,
    ts          TEXT    NOT NULL,
    file_path   TEXT    NOT NULL,
    file_mtime  REAL,
    file_hash   TEXT,
    format      TEXT    NOT NULL,
    source      TEXT    NOT NULL,
    rows_read   INTEGER NOT NULL,
    inserted    INTEGER NOT NULL,
    updated     INTEGER NOT NULL,
    skipped     INTEGER NOT NULL
);
"""

# Partial UNIQUE index: when file_hash is known, (source, hash) must be unique.
_DDL_IMPORTS_IDX_HASH = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_imports_source_hash
    ON imports(source, file_hash)
    WHERE file_hash IS NOT NULL;
"""

# Partial UNIQUE index: when file_hash is unavailable, fall back to
# (source, file_path, file_mtime) as the dedup key.
_DDL_IMPORTS_IDX_PATH = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_imports_source_path_mtime
    ON imports(source, file_path, file_mtime)
    WHERE file_hash IS NULL;
"""

_DDL_CONVERSATIONS = """
CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY,
    title       TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
"""

_DDL_CHAT_MESSAGES = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id              INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT    NOT NULL,
    content         TEXT,
    tool_calls_json TEXT,
    tool_call_id    TEXT,
    created_at      TEXT    NOT NULL
);
"""

_DDL_CHAT_MESSAGES_IDX = """
CREATE INDEX IF NOT EXISTS idx_chatmsg_conv
    ON chat_messages(conversation_id, created_at);
"""

_DDL_CHAT_UPDATE_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS trg_chat_update_conv
AFTER INSERT ON chat_messages
BEGIN
    UPDATE conversations SET updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now')
    WHERE id = NEW.conversation_id;
END;
"""

_ALL_DDL = [
    _DDL_VOCAB_ITEMS, _DDL_EXAMPLES, _DDL_ATTEMPTS,
    _DDL_IMPORTS, _DDL_IMPORTS_IDX_HASH, _DDL_IMPORTS_IDX_PATH,
    _DDL_CONVERSATIONS, _DDL_CHAT_MESSAGES,
    _DDL_CHAT_MESSAGES_IDX, _DDL_CHAT_UPDATE_TRIGGER,
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open (or create) a SQLite database at *db_path*.

    Foreign-key enforcement is enabled immediately via ``PRAGMA foreign_keys``.
    The caller is responsible for closing the connection when done.
    """
    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA foreign_keys = ON;")
    return con


def init_db(con: sqlite3.Connection) -> None:
    """Create all pipeline tables if they do not already exist.

    Safe to call multiple times (idempotent — uses ``CREATE TABLE IF NOT EXISTS``).
    Commits the transaction before returning.
    """
    for ddl in _ALL_DDL:
        con.execute(ddl)
    con.commit()


def list_tables(con: sqlite3.Connection) -> list[str]:
    """Return the names of all user-created tables in the database."""
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
    ).fetchall()
    return [row[0] for row in rows]


# ---------------------------------------------------------------------------
# Source-filter helper shared by all query/reporting functions
# ---------------------------------------------------------------------------

def _build_source_filter(
    source: Optional[str],
    source_prefix: Optional[str],
    default_pipeline_only: bool = True,
) -> tuple[str, tuple, str]:
    """Return ``(where_fragment, extra_params, display_label)``.

    *where_fragment* is a SQL boolean expression on ``v.source`` (alias
    ``v``) suitable for embedding in a ``WHERE`` clause.  *extra_params* is
    a (possibly empty) tuple of bind values.  *display_label* is a
    human-readable description for CLI output.

    Raises ``ValueError`` if both *source* and *source_prefix* are given.
    """
    if source is not None and source_prefix is not None:
        raise ValueError(
            "Provide at most one of 'source' or 'source_prefix', not both."
        )
    if source is not None:
        return "v.source = ?", (source,), source
    if source_prefix is not None:
        return "v.source LIKE ?", (source_prefix + "%",), f"{source_prefix}*"
    if default_pipeline_only:
        return "v.source LIKE 'pipeline:%'", (), "pipeline:* (default)"
    return "1=1", (), "(all sources)"


def count_vocab_for_source(con: sqlite3.Connection, source: str) -> int:
    """Return the number of ``vocab_items`` rows with *source* as their label."""
    row = con.execute(
        "SELECT COUNT(*) FROM vocab_items WHERE source = ?",
        (source,),
    ).fetchone()
    return row[0] if row else 0


def record_import(
    con: sqlite3.Connection,
    *,
    ts: str,
    file_path: str,
    file_mtime: Optional[float],
    file_hash: Optional[str],
    format: str,
    source: str,
    rows_read: int,
    inserted: int,
    updated: int,
    skipped: int,
) -> None:
    """Write one row to the imports ledger (idempotent via INSERT OR IGNORE).

    Duplicate detection uses whichever UNIQUE index applies:

    * ``(source, file_hash)`` — when *file_hash* is not ``None``.
    * ``(source, file_path, file_mtime)`` — fallback when hash is unavailable.

    A duplicate silently produces 0 new rows; no exception is raised.
    The caller must commit the enclosing transaction (or rely on auto-commit).
    """
    con.execute(
        "INSERT OR IGNORE INTO imports "
        "(ts, file_path, file_mtime, file_hash, format, source, "
        " rows_read, inserted, updated, skipped) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ts, file_path, file_mtime, file_hash, format, source,
         rows_read, inserted, updated, skipped),
    )
    con.commit()


def get_latest_pipeline_source(con: sqlite3.Connection) -> Optional[str]:
    """Return the source label of the most recently imported pipeline file.

    Resolution order (most-to-least reliable):

    1. **``imports`` ledger** — ``MAX(ts)`` across rows where
       ``source LIKE 'pipeline:%'``, tie-broken by ``id DESC``.
       This captures every import attempt, including those where all rows were
       already in ``vocab_items`` (``inserted=0, updated=0, skipped=N``).
       If the ``imports`` table does not exist yet (pre-Step-14 DB that has
       not been re-initialised), the query is silently skipped.

    2. **``vocab_items`` fallback** — inferred from ``MAX(created_at)`` /
       ``MAX(id)`` / lexical sort on ``source``.  Used when the ledger is
       absent or empty (legacy databases).

    Returns ``None`` if no pipeline sources are found by either method.
    """
    # ── 1. Imports ledger (preferred) ─────────────────────────────────────
    try:
        row = con.execute(
            "SELECT source FROM imports "
            "WHERE source LIKE 'pipeline:%' "
            "ORDER BY ts DESC, id DESC "
            "LIMIT 1"
        ).fetchone()
        if row:
            return row[0]
    except sqlite3.OperationalError:
        pass   # imports table absent on pre-Step-14 DB — fall through

    # ── 2. vocab_items fallback ────────────────────────────────────────────
    row = con.execute(
        "SELECT source "
        "FROM vocab_items "
        "WHERE source LIKE 'pipeline:%' "
        "GROUP BY source "
        "ORDER BY "
        "    MAX(NULLIF(created_at, '')) DESC, "
        "    MAX(id) DESC, "
        "    source DESC "
        "LIMIT 1"
    ).fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Reporting / stats queries
# ---------------------------------------------------------------------------

#: Items with fewer total attempts than this are excluded from the
#: "most missed all-time" ranking to avoid noise from sparse data.
_MOST_MISSED_MIN_ATTEMPTS: int = 3

# ---------------------------------------------------------------------------
# Adaptive selection constants (select_practice_items)
# ---------------------------------------------------------------------------

#: Rolling window in days used for the adaptive selection query.
_SELECTION_WINDOW_DAYS: int = 30

#: Priority boost weight per unit of near-miss rate
#: (``near_miss_30d / attempts_30d``).  Maximum contribution: this value.
_NEAR_MISS_BOOST: float = 0.3

#: Priority boost weight per unit of article-error rate
#: (``article_30d / attempts_30d``).  Article errors only arise from article
#: drills, which are only offered for noun items, so the boost naturally
#: targets nouns with persistent article confusion without an explicit noun
#: check.  Maximum contribution: this value.
_ARTICLE_BOOST: float = 0.2


def query_stats(
    con: sqlite3.Connection,
    cutoff_iso: str,
    *,
    source: Optional[str] = None,
    source_prefix: Optional[str] = None,
    default_pipeline_only: bool = True,
) -> dict:
    """Return health metrics for the given practice window.

    Parameters
    ----------
    cutoff_iso:
        ISO-8601 timestamp string *generated in Python* (same ``'T'``-
        separator format as stored ``ts`` values).  Only attempts with
        ``ts >= cutoff_iso`` are included in window counts.

    Returns
    -------
    dict with keys:

    * ``filter_label``    — human-readable source description
    * ``vocab_count``     — vocab items matching the source filter
    * ``attempts_count``  — attempts in the window
    * ``accuracy``        — ``AVG(is_correct)`` over the window (0.0 if none)
    * ``near_miss_count`` — attempts tagged ``'near_miss'`` in the window
    * ``near_miss_rate``  — ``near_miss_count / attempts_count`` (0.0 if none)
    * ``last_seen``       — ``MAX(ts)`` across the window, or ``None``
    """
    frag, src_params, label = _build_source_filter(
        source, source_prefix, default_pipeline_only
    )
    sql = (
        "SELECT "
        "    COUNT(DISTINCT v.id)                                                 AS vocab_count, "
        "    COUNT(a.id)                                                          AS attempts_count, "
        "    COALESCE(AVG(a.is_correct), 0.0)                                    AS accuracy, "
        "    COALESCE(SUM(CASE WHEN a.error_tags LIKE '%near_miss%' "
        "                 THEN 1 ELSE 0 END), 0)                                 AS near_miss_count, "
        "    MAX(a.ts)                                                            AS last_seen "
        "FROM vocab_items v "
        "LEFT JOIN attempts a "
        "    ON  a.vocab_id = v.id "
        "    AND a.ts >= ? "
        f"WHERE {frag}"
    )
    params = (cutoff_iso,) + src_params

    old_factory = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(sql, params).fetchone()
    finally:
        con.row_factory = old_factory

    att = row["attempts_count"]
    nm  = row["near_miss_count"]
    return {
        "filter_label":    label,
        "vocab_count":     row["vocab_count"],
        "attempts_count":  att,
        "accuracy":        row["accuracy"],
        "near_miss_count": nm,
        "near_miss_rate":  nm / att if att else 0.0,
        "last_seen":       row["last_seen"],
    }


def query_focus_metrics(
    con: sqlite3.Connection,
    cutoff_iso: str,
    *,
    source: Optional[str] = None,
    source_prefix: Optional[str] = None,
    default_pipeline_only: bool = True,
) -> dict:
    """Return metrics used by the ``focus`` heuristic for the given window.

    Returns
    -------
    dict with keys:

    * ``attempts``           — total attempts in the window
    * ``acc``                — ``AVG(is_correct)`` (0.0 if no attempts)
    * ``near_miss_count``    — attempts tagged ``'near_miss'``
    * ``near_miss_rate``     — ``near_miss_count / attempts`` (0.0 if none)
    * ``article_attempts``   — attempts where ``drill_type IN ('article','mcq_article')``
    * ``article_wrong``      — article attempts that were wrong AND tagged ``'article'``
    * ``article_error_rate`` — ``article_wrong / article_attempts`` (0.0 if none)
    """
    frag, src_params, _ = _build_source_filter(
        source, source_prefix, default_pipeline_only
    )
    sql = (
        "SELECT "
        "    COUNT(a.id)                                                          AS attempts, "
        "    COALESCE(AVG(a.is_correct), 0.0)                                    AS acc, "
        "    COALESCE(SUM(CASE WHEN a.error_tags LIKE '%near_miss%' "
        "                 THEN 1 ELSE 0 END), 0)                                 AS near_miss_count, "
        "    COALESCE(SUM(CASE WHEN a.drill_type IN ('article', 'mcq_article') "
        "                 THEN 1 ELSE 0 END), 0)                                 AS article_attempts, "
        "    COALESCE(SUM(CASE WHEN a.drill_type IN ('article', 'mcq_article') "
        "                      AND a.is_correct = 0 "
        "                      AND a.error_tags LIKE '%article%' "
        "                 THEN 1 ELSE 0 END), 0)                                 AS article_wrong "
        "FROM vocab_items v "
        "LEFT JOIN attempts a "
        "    ON  a.vocab_id = v.id "
        "    AND a.ts >= ? "
        f"WHERE {frag}"
    )
    params = (cutoff_iso,) + src_params

    old_factory = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(sql, params).fetchone()
    finally:
        con.row_factory = old_factory

    att = row["attempts"]
    art = row["article_attempts"]
    art_wrong = row["article_wrong"]
    return {
        "attempts":           att,
        "acc":                row["acc"],
        "near_miss_count":    row["near_miss_count"],
        "near_miss_rate":     row["near_miss_count"] / att if att else 0.0,
        "article_attempts":   art,
        "article_wrong":      art_wrong,
        "article_error_rate": art_wrong / art if art else 0.0,
    }


def query_worst_items(
    con: sqlite3.Connection,
    cutoff_iso: str,
    n: int,
    *,
    source: Optional[str] = None,
    source_prefix: Optional[str] = None,
    default_pipeline_only: bool = True,
    min_attempts: int = 0,
) -> list[dict]:
    """Return up to *n* worst-performing vocab items in the time window.

    Ordered by:

    1. Lowest window accuracy (``COALESCE(AVG, 0.0)`` — unseen = weakest)
    2. Oldest ``last_seen`` (``NULL`` sorts first — never-seen before stale)
    3. Highest attempt count (more data beats sparse ties)

    When *min_attempts* > 0, items with fewer window attempts than that
    threshold are excluded (useful for export packs where only practised
    items with meaningful signal should be surfaced).

    Each dict has keys: ``id``, ``de_display``, ``en``, ``acc_window``,
    ``attempts_window``, ``near_miss_window``, ``last_seen``.
    """
    frag, src_params, _ = _build_source_filter(
        source, source_prefix, default_pipeline_only
    )
    sql = (
        "SELECT "
        "    v.id, "
        "    COALESCE(NULLIF(v.de_mit_artikel, ''), v.de)   AS de_display, "
        "    v.en, "
        "    COALESCE(AVG(a.is_correct), 0.0)               AS acc_window, "
        "    COUNT(a.id)                                     AS attempts_window, "
        "    COALESCE(SUM(CASE WHEN a.error_tags LIKE '%near_miss%' "
        "                 THEN 1 ELSE 0 END), 0)             AS near_miss_window, "
        "    MAX(a.ts)                                       AS last_seen "
        "FROM vocab_items v "
        "LEFT JOIN attempts a "
        "    ON  a.vocab_id = v.id "
        "    AND a.ts >= ? "
        f"WHERE {frag} "
        "GROUP BY v.id"
    )
    params = (cutoff_iso,) + src_params
    if min_attempts > 0:
        sql    += " HAVING COUNT(a.id) >= ?"
        params  = params + (min_attempts,)
    sql    += " ORDER BY acc_window ASC, last_seen ASC, attempts_window DESC LIMIT ?"
    params  = params + (n,)

    old_factory = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(sql, params).fetchall()
    finally:
        con.row_factory = old_factory

    return [dict(row) for row in rows]


def query_most_missed_alltime(
    con: sqlite3.Connection,
    top_n: int = 5,
    *,
    min_attempts: int = _MOST_MISSED_MIN_ATTEMPTS,
    source: Optional[str] = None,
    source_prefix: Optional[str] = None,
    default_pipeline_only: bool = False,
) -> list[dict]:
    """Return the *top_n* most-missed items across all time.

    Items with fewer than *min_attempts* total attempts are excluded to
    avoid noise from vocabulary that has barely been practised.

    By default (``default_pipeline_only=False``, no *source* / *source_prefix*)
    no source filter is applied — "all time" means all sources.  Pass
    *source* / *source_prefix* or set *default_pipeline_only=True* to
    restrict to a specific vocabulary set (e.g. for the ``export-pack``
    ``filtered`` scope).

    Each dict has keys: ``id``, ``de_display``, ``miss_count``,
    ``total_attempts``, ``acc_alltime``.
    """
    frag, src_params, _ = _build_source_filter(
        source, source_prefix, default_pipeline_only
    )
    sql = (
        "SELECT "
        "    v.id, "
        "    COALESCE(NULLIF(v.de_mit_artikel, ''), v.de)  AS de_display, "
        "    SUM(1 - a.is_correct)                         AS miss_count, "
        "    COUNT(a.id)                                   AS total_attempts, "
        "    AVG(a.is_correct)                             AS acc_alltime "
        "FROM vocab_items v "
        "INNER JOIN attempts a ON a.vocab_id = v.id "
        f"WHERE {frag} "
        "GROUP BY v.id "
        "HAVING COUNT(a.id) >= ? "
        "ORDER BY miss_count DESC, total_attempts DESC "
        "LIMIT ?"
    )

    old_factory = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(sql, src_params + (min_attempts, top_n)).fetchall()
    finally:
        con.row_factory = old_factory

    return [dict(row) for row in rows]


def fetch_vocab_by_ids(
    con: sqlite3.Connection,
    ids: list[int],
) -> list[dict]:
    """Return full ``vocab_items`` rows for the given *ids*.

    Returns dicts with keys: ``id``, ``de``, ``de_mit_artikel``, ``en``,
    ``af``, ``notes``, ``source``.  Order is not guaranteed — callers
    should build a ``{id: row}`` lookup dict when they need random access.

    Returns an empty list immediately when *ids* is empty.
    """
    if not ids:
        return []
    placeholders = ", ".join("?" * len(ids))
    sql = (
        f"SELECT id, de, de_mit_artikel, en, af, notes, source "
        f"FROM vocab_items WHERE id IN ({placeholders})"
    )
    old_factory = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(sql, ids).fetchall()
    finally:
        con.row_factory = old_factory
    return [dict(row) for row in rows]


def fetch_vocab_items_all(
    con: sqlite3.Connection,
    *,
    source: Optional[str] = None,
    source_prefix: Optional[str] = None,
    default_pipeline_only: bool = True,
    limit: Optional[int] = None,
) -> list[dict]:
    """Return all vocab items matching the source filter, ordered by ``id``.

    Unlike :func:`select_practice_items`, this performs no priority ranking
    — every matching row is returned (or up to *limit* rows when specified).
    Intended for batch operations such as ``generate-examples``.

    Each dict has keys: ``id``, ``de``, ``de_mit_artikel``, ``en``, ``af``,
    ``notes``, ``source``.
    """
    frag, src_params, _ = _build_source_filter(
        source, source_prefix, default_pipeline_only
    )
    sql = (
        f"SELECT v.id, v.de, v.de_mit_artikel, v.en, v.af, v.notes, v.source "
        f"FROM vocab_items v WHERE {frag} ORDER BY v.id ASC"
    )
    params: tuple = src_params
    if limit is not None:
        sql    += " LIMIT ?"
        params  = params + (int(limit),)

    old_factory = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(sql, params).fetchall()
    finally:
        con.row_factory = old_factory
    return [dict(row) for row in rows]


def fetch_existing_example_sentences(
    con: sqlite3.Connection,
    vocab_id: int,
) -> set[str]:
    """Return the set of ``de_sentence`` strings already stored for *vocab_id*.

    Used by ``generate-examples`` to avoid inserting duplicates.  The
    ``examples`` table has no UNIQUE constraint on ``(vocab_id, de_sentence)``
    so dedup must be enforced in Python.
    """
    rows = con.execute(
        "SELECT de_sentence FROM examples "
        "WHERE vocab_id = ? AND de_sentence IS NOT NULL",
        (vocab_id,),
    ).fetchall()
    return {row[0] for row in rows}


def insert_example(
    con: sqlite3.Connection,
    *,
    vocab_id: int,
    de_sentence: str,
    en_sentence: str = "",
    af_sentence: str = "",
    difficulty: int = 2,
    style_tag: str = "template",
) -> None:
    """Insert a single row into the ``examples`` table.

    Does **not** commit — the caller owns the transaction.  Batch up many
    calls and call ``con.commit()`` once for efficiency.

    Blank *en_sentence* / *af_sentence* strings are stored as ``NULL``
    (preferred over empty string for optional fields).
    """
    con.execute(
        "INSERT INTO examples "
        "(vocab_id, de_sentence, en_sentence, af_sentence, difficulty, style_tag) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            vocab_id,
            de_sentence,
            en_sentence or None,
            af_sentence or None,
            difficulty,
            style_tag,
        ),
    )


def select_practice_items(
    con: sqlite3.Connection,
    n: int,
    *,
    source: Optional[str] = None,
    source_prefix: Optional[str] = None,
    default_pipeline_only: bool = True,
    seed: Optional[int] = None,
) -> list[dict]:
    """Return up to *n* vocab items ranked for adaptive practice.

    Items are ordered by a composite **priority score** (higher = shown
    sooner) computed over the last ``_SELECTION_WINDOW_DAYS`` days::

        base              = 1.0 - COALESCE(acc_window, 0.0)
        near_miss_rate    = near_miss_window / attempts_window
        article_err_rate  = article_wrong_window / article_attempts_window  (nouns only)
        priority          = base
                          + near_miss_rate   * _NEAR_MISS_BOOST
                          + article_err_rate * _ARTICLE_BOOST

    Denominators:

    * *near-miss rate*: ``attempts_window`` (all drills) — near-miss is
      meaningful against all recent attempts.
    * *article-error rate*: ``article_attempts_window`` (article drills only)
      — avoids dilution by ``en_to_de`` drills that dominate total attempts.

    Article boost is gated on the noun predicate
    (``notes LIKE '%Substantiv%'`` or ``de_mit_artikel`` starts with a
    definite article).  Non-noun items have ``article_attempts_window = 0``
    in practice, so the gate is belt-and-suspenders.

    Items with *no* window attempts score ``priority = 1.0`` (maximum base,
    zero boosts) and share the top bucket with always-wrong items.

    Secondary key: ``last_seen`` ascending (``NULL`` sorts first).
    Final tie-break: ``random.Random(seed).shuffle`` — reproducible with ``--seed``.

    Parameters
    ----------
    con:
        Open ``sqlite3.Connection`` (caller owns lifecycle).
    n:
        Maximum number of items to return.
    source:
        Exact ``source`` column match.  Mutually exclusive with
        *source_prefix*.
    source_prefix:
        Prefix match (``WHERE source LIKE ?``).  Mutually exclusive with
        *source*.
    default_pipeline_only:
        Restrict to ``source LIKE 'pipeline:%'`` when no other filter is
        given.  Set to ``False`` to select from all sources.
    seed:
        Integer seed for the Python shuffle tie-break.  ``None`` gives a
        non-deterministic session.

    Returns
    -------
    list[dict]
        Each dict has keys: ``id``, ``de``, ``de_mit_artikel``, ``en``,
        ``notes``, ``source``.  At most *n* items; may be fewer if the
        filtered table has fewer rows.
    """
    # ── Build WHERE clause ────────────────────────────────────────────────
    if source is not None and source_prefix is not None:
        raise ValueError(
            "Provide at most one of 'source' or 'source_prefix', not both."
        )

    if source is not None:
        where  = "WHERE v.source = ?"
        params: tuple = (source,)
    elif source_prefix is not None:
        where  = "WHERE v.source LIKE ?"
        params = (source_prefix + "%",)
    elif default_pipeline_only:
        where  = "WHERE v.source LIKE 'pipeline:%'"
        params = ()
    else:
        where  = ""
        params = ()

    # ── Python-computed cutoff (avoids SQLite datetime() format mismatch) ─
    # SQLite's datetime('now', '-N days') uses a space separator while our
    # stored ts values use ISO 'T'.  Computing the cutoff in Python and
    # passing it as a parameter guarantees byte-accurate comparisons.
    cutoff_iso = (
        datetime.now(timezone.utc) - timedelta(days=_SELECTION_WINDOW_DAYS)
    ).replace(microsecond=0).isoformat()

    # ── CTE-based priority SQL ────────────────────────────────────────────
    #
    # The CTE "agg" computes five fine-grained aggregates over the window:
    #
    #   attempts_window         — total drills in the window
    #   near_miss_window        — drills tagged near_miss
    #   article_attempts_window — drills where drill_type IN ('article',
    #                             'mcq_article')  — both drill types test the
    #                             same article-recall skill and should pool
    #                             their signal.
    #   article_wrong_window    — article / mcq_article drills that were wrong
    #                             AND tagged 'article' or 'mcq article' (the
    #                             '%article%' LIKE catches both tag formats);
    #   last_seen               — most recent attempt timestamp
    #
    # The outer SELECT then computes priority using the correct denominators:
    #
    #   near_miss_rate   = near_miss_window / attempts_window
    #   article_err_rate = article_wrong_window / article_attempts_window
    #
    # The article boost is gated on the noun predicate so that non-noun items
    # (which have article_attempts_window = 0 anyway) never receive it even
    # if historical data contains unexpected article-drill records.
    #
    # Boost constants are f-string interpolated from Python so the SQL and
    # the module constants stay in sync; they are not user input.
    #
    # All matching rows are fetched without LIMIT so the Python shuffle can
    # cover the full candidate set before trimming to n.
    sql = (
        "WITH agg AS ( "
        "    SELECT "
        "        v.id, v.de, v.de_mit_artikel, v.en, v.notes, v.source, "
        "        COALESCE(AVG(a.is_correct), 0.0)                            AS acc, "
        "        COUNT(a.id)                                                  AS attempts_window, "
        "        COALESCE(SUM(CASE WHEN a.error_tags LIKE '%near_miss%' "
        "                     THEN 1 ELSE 0 END), 0)                         AS near_miss_window, "
        "        COALESCE(SUM(CASE WHEN a.drill_type IN ('article', 'mcq_article') "
        "                     THEN 1 ELSE 0 END), 0)                         AS article_attempts_window, "
        "        COALESCE(SUM(CASE WHEN a.drill_type IN ('article', 'mcq_article') "
        "                          AND a.is_correct = 0 "
        "                          AND a.error_tags LIKE '%article%' "
        "                     THEN 1 ELSE 0 END), 0)                         AS article_wrong_window, "
        "        MAX(a.ts)                                                    AS last_seen "
        "    FROM vocab_items v "
        "    LEFT JOIN attempts a "
        "        ON  a.vocab_id = v.id "
        "        AND a.ts >= ? "
        f"    {where} "
        "    GROUP BY v.id "
        ") "
        "SELECT *, "
        "    ( "
        "        (1.0 - acc) "
        # near-miss boost: rate over ALL window attempts
        "        + CASE WHEN attempts_window > 0 "
        "               THEN (near_miss_window * 1.0 / attempts_window) "
        f"                    * {_NEAR_MISS_BOOST} "
        "               ELSE 0.0 END "
        # article-error boost: rate over article-drill attempts only, nouns only
        "        + CASE WHEN ( "
        "                  notes LIKE '%Substantiv%' "
        "                  OR TRIM(de_mit_artikel) LIKE 'der %' "
        "                  OR TRIM(de_mit_artikel) LIKE 'die %' "
        "                  OR TRIM(de_mit_artikel) LIKE 'das %' "
        "              ) AND article_attempts_window > 0 "
        "               THEN (article_wrong_window * 1.0 / article_attempts_window) "
        f"                    * {_ARTICLE_BOOST} "
        "               ELSE 0.0 END "
        "    ) AS priority "
        "FROM agg "
        "ORDER BY priority DESC, last_seen ASC"
    )

    all_params = (cutoff_iso,) + params

    old_factory = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(sql, all_params).fetchall()
    finally:
        con.row_factory = old_factory

    # Convert to plain dicts — callers only need the vocab fields
    items = [
        {
            "id":             row["id"],
            "de":             row["de"],
            "de_mit_artikel": row["de_mit_artikel"],
            "en":             row["en"],
            "notes":          row["notes"],
            "source":         row["source"],
        }
        for row in rows
    ]

    # ── Shuffle within ties, then enforce priority order ──────────────────
    # Shuffle first so equal-(priority, last_seen) items are randomised
    # (reproducibly when seed is set).  Re-sort with a stable key so the
    # shuffle result is preserved within each tie group.
    # Negate priority so that higher priority → smaller sort key → earlier.
    # NULL last_seen → "" which sorts before any real ISO timestamp, keeping
    # never-seen items at the front within each priority bucket.
    rng = random.Random(seed)
    rng.shuffle(items)
    pri_map  = {row["id"]: row["priority"]          for row in rows}
    last_map = {row["id"]: (row["last_seen"] or "")  for row in rows}
    items.sort(key=lambda it: (-pri_map[it["id"]], last_map[it["id"]]))

    return items[:n]


# ---------------------------------------------------------------------------
# Chat / conversation CRUD
# ---------------------------------------------------------------------------

def create_conversation(con: sqlite3.Connection, title: str) -> int:
    """Insert a new conversation and return its ``id``."""
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cur = con.execute(
        "INSERT INTO conversations (title, created_at, updated_at) "
        "VALUES (?, ?, ?)",
        (title, now, now),
    )
    con.commit()
    return cur.lastrowid


def save_message(
    con: sqlite3.Connection,
    conversation_id: int,
    role: str,
    content: str | None,
    *,
    tool_calls_json: str | None = None,
    tool_call_id: str | None = None,
) -> int:
    """Insert a chat message and return its ``id``.

    The ``trg_chat_update_conv`` trigger automatically updates the
    parent conversation's ``updated_at`` timestamp.
    """
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cur = con.execute(
        "INSERT INTO chat_messages "
        "(conversation_id, role, content, tool_calls_json, tool_call_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (conversation_id, role, content, tool_calls_json, tool_call_id, now),
    )
    con.commit()
    return cur.lastrowid


def load_messages(con: sqlite3.Connection, conversation_id: int) -> list[dict]:
    """Return all messages for a conversation, ordered by creation time."""
    old_factory = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT id, role, content, tool_calls_json, tool_call_id, created_at "
            "FROM chat_messages "
            "WHERE conversation_id = ? "
            "ORDER BY created_at, id",
            (conversation_id,),
        ).fetchall()
    finally:
        con.row_factory = old_factory
    return [dict(row) for row in rows]


def list_conversations(
    con: sqlite3.Connection, max_age_days: int = 30
) -> list[dict]:
    """Return conversations updated within *max_age_days*, newest first."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=max_age_days)
    ).replace(microsecond=0).isoformat()
    old_factory = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT id, title, created_at, updated_at "
            "FROM conversations "
            "WHERE updated_at >= ? "
            "ORDER BY updated_at DESC",
            (cutoff,),
        ).fetchall()
    finally:
        con.row_factory = old_factory
    return [dict(row) for row in rows]


def update_conversation_title(
    con: sqlite3.Connection, conversation_id: int, title: str
) -> None:
    """Update the title of an existing conversation."""
    con.execute(
        "UPDATE conversations SET title = ? WHERE id = ?",
        (title, conversation_id),
    )
    con.commit()


def delete_conversation(con: sqlite3.Connection, conversation_id: int) -> None:
    """Delete a conversation and all its messages (``ON DELETE CASCADE``)."""
    con.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    con.commit()


def purge_old_conversations(
    con: sqlite3.Connection, max_age_days: int = 5
) -> int:
    """Hard-delete conversations not updated within *max_age_days*.

    Returns the number of conversations deleted.  Child ``chat_messages``
    rows are removed automatically via ``ON DELETE CASCADE``.
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=max_age_days)
    ).replace(microsecond=0).isoformat()
    cur = con.execute(
        "DELETE FROM conversations WHERE updated_at < ?", (cutoff,),
    )
    con.commit()
    return cur.rowcount
