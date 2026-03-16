"""
ui_utils.py — Shared utilities and sidebar renderer for all Streamlit pages.

Lives at the project root (NOT inside pages/) so Streamlit never treats it
as a navigation page.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

from german_pipeline import storage

# Default DB path
DEFAULT_DB = Path("output/german.db")

# Maps mode string → allowed_types set for drills.pick_drill_with_pool
MODE_ALLOWED_TYPES: dict[str, set[str] | None] = {
    "mixed":     None,
    "translate": {"en_to_de"},
    "articles":  {"article", "mcq_article"},
    "cloze":     {"cloze"},
    "mcq":       {"mcq_en_to_de", "mcq_article"},
}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def cutoff_iso(days: int) -> str:
    """Return an ISO-8601 UTC cutoff timestamp *days* ago."""
    return (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).replace(microsecond=0).isoformat()


def get_db_path() -> str:
    """Return the DB path from session state, falling back to the default."""
    return st.session_state.get("db_path", str(DEFAULT_DB))


def open_db(db_path: str | None = None) -> sqlite3.Connection:
    """Open and return a SQLite connection to the practice DB."""
    path = db_path or get_db_path()
    return storage.connect(path)


def list_sources(con: sqlite3.Connection) -> list[str]:
    """Return all distinct source labels in vocab_items, sorted."""
    rows = con.execute(
        "SELECT DISTINCT source FROM vocab_items ORDER BY source"
    ).fetchall()
    return [r[0] for r in rows]


def auto_resolve_source(
    con: sqlite3.Connection,
    source: str | None,
    source_prefix: str | None,
) -> tuple[str | None, str | None]:
    """Auto-select the latest pipeline source when no filter is given."""
    if source is None and source_prefix is None:
        latest = storage.get_latest_pipeline_source(con)
        if latest is None:
            raise ValueError(
                "No pipeline sources found in DB. "
                "Import a vocabulary file first."
            )
        if storage.count_vocab_for_source(con, latest) == 0:
            return None, "pipeline:"
        return latest, None
    return source, source_prefix


def fmt_rate(rate: float) -> str:
    """Format 0.0–1.0 as a whole-percent string: '68%'."""
    return f"{rate * 100:.0f}%"


def fmt_ts(ts: str | None) -> str:
    """Format an ISO timestamp as YYYY-MM-DD, or '—' if None."""
    return ts[:10] if ts else "—"


# ---------------------------------------------------------------------------
# Sidebar renderer — call once per page, right after st.set_page_config
# ---------------------------------------------------------------------------

def render_sidebar() -> None:
    """Inject global CSS and render the consistent sidebar on every page."""

    # ── Global CSS ──────────────────────────────────────────────────────────
    st.markdown("""
<style>
/* ── Primary accent — replaces config.toml primaryColor so the native
   theme toggle (⋮ menu) stays visible. ──────────────────────────── */
:root { --primary-color: #3182CE !important; }

/* Nav container */
[data-testid="stSidebarNav"] {
    padding-top: 0.25rem;
    padding-bottom: 0.5rem;
}
/* Each nav link */
[data-testid="stSidebarNavLink"] {
    border-radius: 6px;
    padding: 0.45rem 0.9rem;
    margin: 2px 6px;
    transition: background 0.15s ease, border-left 0.1s ease;
    border-left: 3px solid transparent;
    font-size: 0.9rem;
    letter-spacing: 0.01em;
}
/* Hover */
[data-testid="stSidebarNavLink"]:hover {
    background: rgba(255, 255, 255, 0.07);
    border-left: 3px solid rgba(49, 130, 206, 0.5);
}
/* Active / selected page */
[data-testid="stSidebarNavLink"][aria-selected="true"] {
    background: rgba(49, 130, 206, 0.18);
    border-left: 3px solid #3182CE;
    font-weight: 600;
}
/* Remove top padding from sidebar */
[data-testid="stSidebar"] > div:first-child {
    padding-top: 0;
}

/* ── Sliders — refined, modern look ─────────────────────── */

/* Label: uppercase, muted, consistent with section labels */
[data-testid="stSlider"] label {
    font-size: 0.72rem !important;
    font-weight: 600 !important;
    color: rgba(255,255,255,0.38) !important;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 0.3rem !important;
}

/* Track container: slim it down */
[data-testid="stSlider"] [data-baseweb="slider"] > div:first-child {
    height: 3px !important;
    border-radius: 3px !important;
    top: 50% !important;
}
/* Track background (unfilled) */
[data-testid="stSlider"] [data-baseweb="slider"] > div:first-child > div:first-child {
    height: 3px !important;
    background: rgba(255,255,255,0.08) !important;
    border-radius: 3px !important;
}
/* Filled portion of track */
[data-testid="stSlider"] [data-baseweb="slider"] > div:first-child > div:first-child > div {
    background: #3182CE !important;
    border-radius: 3px !important;
}

/* Thumb: crisp circle with glow */
[data-testid="stSlider"] [role="slider"] {
    background: #ffffff !important;
    border: 2.5px solid #3182CE !important;
    border-radius: 50% !important;
    width: 18px !important;
    height: 18px !important;
    box-shadow:
        0 1px 5px rgba(0,0,0,0.35),
        0 0 0 3px rgba(49,130,206,0.15) !important;
    /* box-shadow only — no transform, which causes the thumb to jump */
    transition: box-shadow 0.15s ease !important;
    cursor: grab !important;
    outline: none !important;
}
/* Hover: widen the outer glow ring, never move the element */
[data-testid="stSlider"] [role="slider"]:hover {
    box-shadow:
        0 2px 10px rgba(0,0,0,0.4),
        0 0 0 6px rgba(49,130,206,0.28) !important;
}
[data-testid="stSlider"] [role="slider"]:active {
    cursor: grabbing !important;
    box-shadow:
        0 1px 5px rgba(0,0,0,0.35),
        0 0 0 4px rgba(49,130,206,0.45) !important;
}

/* Value bubble — broad selectors to win against Streamlit's inline primaryColor */
[data-testid="stThumbValue"],
[data-testid="stThumbValue"] > div,
[data-testid="stThumbValue"] span,
[data-testid="stThumbValue"] * {
    background: #0D1220 !important;
    border: 1px solid rgba(49,130,206,0.4) !important;
    border-radius: 5px !important;
    color: #ffffff !important;
    font-size: 0.72rem !important;
    font-weight: 800 !important;
    letter-spacing: 0.03em !important;
    padding: 0.1rem 0.5rem !important;
    box-shadow: 0 2px 6px rgba(0,0,0,0.4) !important;
}
/* Fallback: BaseWeb tooltip element used in some Streamlit builds */
[data-testid="stSlider"] [role="tooltip"],
[data-testid="stSlider"] [role="tooltip"] * {
    color: #ffffff !important;
    font-weight: 800 !important;
    background: #0D1220 !important;
    border: 1px solid rgba(49,130,206,0.4) !important;
    border-radius: 5px !important;
    font-size: 0.72rem !important;
}

/* Min / max tick labels */
[data-testid="stTickBar"] {
    color: rgba(255,255,255,0.18) !important;
    font-size: 0.65rem !important;
    padding-top: 0.3rem !important;
}

/* ── Page title headings (##) — match Home hero boldness ────── */
[data-testid="stMainBlockContainer"] h2,
[data-testid="stVerticalBlock"] h2 {
    font-weight: 800 !important;
    color: var(--text-color, rgba(255,255,255,0.95)) !important;
    letter-spacing: -0.015em !important;
    line-height: 1.2 !important;
}

/* ── Sidebar DB status card ────────────────────────────────── */
.db-status-card {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 8px;
    padding: 0.7rem 0.9rem;
    margin: 0 0.1rem 0.6rem;
    font-size: 0.82rem;
}
.db-status-row {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    margin-bottom: 0.5rem;
}
.db-status-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    display: inline-block;
    flex-shrink: 0;
}
.db-status-name { font-weight: 600; color: rgba(255,255,255,0.85); }
.db-stats-grid {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 0.3rem;
    text-align: center;
}
.db-stat-lbl {
    color: rgba(255,255,255,0.45);
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}
.db-stat-val {
    color: #fff;
    font-weight: 700;
    font-size: 1rem;
}
.db-stat-val-sm { font-size: 0.82rem; margin-top: 0.1rem; }

/* ══════════════════════════════════════════════════════════════
   LIGHT MODE OVERRIDES
   Streamlit sets [data-theme="light"] on <html> when the user
   switches via the ⋮ → Settings menu.
   ══════════════════════════════════════════════════════════════ */

/* Nav links */
[data-theme="light"] [data-testid="stSidebarNavLink"]:hover {
    background: rgba(0,0,0,0.05);
    border-left: 3px solid rgba(49,130,206,0.5);
}
[data-theme="light"] [data-testid="stSidebarNavLink"][aria-selected="true"] {
    background: rgba(49,130,206,0.14);
}

/* Sidebar DB status card */
[data-theme="light"] .db-status-card {
    background: rgba(0,0,0,0.03);
    border-color: rgba(0,0,0,0.1);
}
[data-theme="light"] .db-status-name { color: rgba(0,0,0,0.75); }
[data-theme="light"] .db-stat-lbl    { color: rgba(0,0,0,0.45); }
[data-theme="light"] .db-stat-val    { color: rgba(0,0,0,0.85); }

/* Slider label */
[data-theme="light"] [data-testid="stSlider"] label {
    color: rgba(0,0,0,0.5) !important;
}

/* Slider track filled portion — keep blue */
[data-theme="light"] [data-testid="stSlider"] [data-baseweb="slider"] > div:first-child > div:first-child > div {
    background: #3182CE !important;
}

/* Thumb */
[data-theme="light"] [data-testid="stSlider"] [role="slider"] {
    border-color: #3182CE !important;
}

/* Value bubble */
[data-theme="light"] [data-testid="stThumbValue"],
[data-theme="light"] [data-testid="stThumbValue"] > div,
[data-theme="light"] [data-testid="stThumbValue"] span,
[data-theme="light"] [data-testid="stThumbValue"] * {
    background: #EBF4FF !important;
    color: #2B6CB0 !important;
    border-color: rgba(49,130,206,0.45) !important;
}
[data-theme="light"] [data-testid="stSlider"] [role="tooltip"],
[data-theme="light"] [data-testid="stSlider"] [role="tooltip"] * {
    background: #EBF4FF !important;
    color: #2B6CB0 !important;
}

/* Tick bar */
[data-theme="light"] [data-testid="stTickBar"] {
    color: rgba(0,0,0,0.3) !important;
}

/* ── Plotly charts — light mode text & grid ──────────────────── */
/* Streamlit renders Plotly inline (not iframed) so CSS reaches SVG */
[data-theme="light"] .js-plotly-plot .xtick text,
[data-theme="light"] .js-plotly-plot .ytick text,
[data-theme="light"] .js-plotly-plot .legendtext,
[data-theme="light"] .js-plotly-plot .g-xtitle text,
[data-theme="light"] .js-plotly-plot .g-ytitle text,
[data-theme="light"] .js-plotly-plot .annotation-text text,
[data-theme="light"] .js-plotly-plot .cbaxis text {
    fill: rgba(50,50,50,0.72) !important;
}
[data-theme="light"] .js-plotly-plot .gridlayer path {
    stroke: rgba(0,0,0,0.07) !important;
}
[data-theme="light"] .js-plotly-plot .zerolinelayer path {
    stroke: rgba(0,0,0,0.12) !important;
}
[data-theme="light"] .js-plotly-plot .bg {
    fill: rgba(0,0,0,0.02) !important;
}
</style>
""", unsafe_allow_html=True)

    # ── Header banner ────────────────────────────────────────────────────────
    st.sidebar.markdown("""
<div style="
    background: linear-gradient(135deg, #1a365d 0%, #2b6cb0 100%);
    border-radius: 8px;
    padding: 1rem 1.1rem 0.9rem;
    margin-bottom: 0.75rem;
    margin-top: -0.5rem;
">
    <div style="font-size:1.6rem; line-height:1;">🇩🇪</div>
    <div style="
        color: #ffffff;
        font-size: 1.05rem;
        font-weight: 700;
        margin-top: 0.35rem;
        letter-spacing: 0.02em;
    ">German Learning</div>
    <div style="
        color: rgba(255,255,255,0.6);
        font-size: 0.72rem;
        margin-top: 0.15rem;
        letter-spacing: 0.03em;
        text-transform: uppercase;
    ">Vocabulary · Practice · Progress</div>
</div>
""", unsafe_allow_html=True)

    # ── DB status card ───────────────────────────────────────────────────────
    db_path = get_db_path()
    db_file = Path(db_path)

    if db_file.exists():
        try:
            con = storage.connect(db_path)
            vocab_count   = con.execute("SELECT COUNT(*) FROM vocab_items").fetchone()[0]
            last_ts       = con.execute("SELECT MAX(ts) FROM attempts").fetchone()[0]
            attempt_count = con.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
            con.close()
            last_date  = last_ts[:10] if last_ts else "never"
            dot_color  = "#48BB78"
            status_txt = "Connected"
        except Exception:
            vocab_count = attempt_count = "—"
            last_date   = "—"
            dot_color   = "#FC8181"
            status_txt  = "Not initialised"
    else:
        vocab_count = attempt_count = "—"
        last_date   = "—"
        dot_color   = "#A0AEC0"
        status_txt  = "No database"

    st.sidebar.markdown(f"""
<div class="db-status-card">
    <div class="db-status-row">
        <span class="db-status-dot" style="background:{dot_color};"></span>
        <span class="db-status-name">{status_txt}</span>
    </div>
    <div class="db-stats-grid">
        <div>
            <div class="db-stat-lbl">Vocab</div>
            <div class="db-stat-val">{vocab_count}</div>
        </div>
        <div>
            <div class="db-stat-lbl">Attempts</div>
            <div class="db-stat-val">{attempt_count}</div>
        </div>
        <div>
            <div class="db-stat-lbl">Last seen</div>
            <div class="db-stat-val db-stat-val-sm">{last_date}</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

    # ── DB settings expander ─────────────────────────────────────────────────
    with st.sidebar.expander("⚙️ Database settings"):
        db_path_input = st.text_input(
            "Database path",
            value=db_path,
            help="Path to the SQLite practice database.",
            label_visibility="collapsed",
            key="_sidebar_db_path",
        )
        # Persist immediately so other widgets on the page read the updated value
        st.session_state["db_path"] = db_path_input

        if st.button("Initialize DB", key="_sidebar_init_db",
                     help="Create tables if they don't exist yet."):
            try:
                con = storage.connect(db_path_input)
                storage.init_db(con)
                con.close()
                st.success("DB initialised.")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

