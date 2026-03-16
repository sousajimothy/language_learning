"""
app.py — Streamlit entry point for the German Language Learning app.

Uses explicit st.navigation() so Streamlit never auto-discovers pages/utils.py
or pages/_utils.py, eliminating the duplicate-slug conflict.

Run with:
    micromamba run -n language_learning_env streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

# ---------------------------------------------------------------------------
# Page config — must be the very first Streamlit call
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="German Learning",
    page_icon="🇩🇪",
    layout="wide",
    initial_sidebar_state="expanded",
)

from ui_utils import render_sidebar  # noqa: E402

# Sidebar renders once here in the shell → appears on every page automatically
render_sidebar()

# ---------------------------------------------------------------------------
# Home page
# ---------------------------------------------------------------------------

def home_page() -> None:
    from datetime import datetime, timezone
    from pathlib import Path
    from ui_utils import get_db_path
    from german_pipeline import storage

    # ── CSS ──────────────────────────────────────────────────────────────────
    st.markdown("""
<style>
/* ── Hero banner ──────────────────────────────────────────────────── */
.home-hero {
    background: linear-gradient(135deg, #1a365d 0%, #2b6cb0 60%, #3182CE 100%);
    border-radius: 12px;
    padding: 1.8rem 2rem 1.6rem;
    margin-bottom: 1.5rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
}
.hero-left { display: flex; align-items: center; gap: 1.1rem; }
.hero-flag { font-size: 2.6rem; line-height: 1; }
.hero-title {
    font-size: 1.7rem;
    font-weight: 800;
    color: #fff;
    letter-spacing: -0.01em;
    line-height: 1.15;
}
.hero-sub {
    font-size: 0.8rem;
    color: rgba(255,255,255,0.55);
    letter-spacing: 0.06em;
    text-transform: uppercase;
    margin-top: 0.25rem;
}
.hero-date {
    text-align: right;
    color: rgba(255,255,255,0.4);
    font-size: 0.8rem;
    line-height: 1.6;
}
/* ── Stat cards ───────────────────────────────────────────────────── */
.stat-card {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 10px;
    padding: 0.9rem 1rem 0.75rem;
    text-align: center;
}
.stat-card .sc-num {
    font-size: 2rem;
    font-weight: 800;
    line-height: 1;
    color: #fff;
}
.stat-card .sc-lbl {
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.38);
    margin-top: 0.3rem;
}
.stat-card .sc-sub {
    font-size: 0.72rem;
    color: rgba(255,255,255,0.3);
    margin-top: 0.15rem;
}
/* ── Workflow stepper ─────────────────────────────────────────────── */
.stepper {
    display: flex;
    align-items: flex-start;
    gap: 0;
    margin: 0.5rem 0 0.25rem;
}
.step {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    position: relative;
}
.step:not(:last-child)::after {
    content: '';
    position: absolute;
    top: 14px;
    left: calc(50% + 14px);
    right: calc(-50% + 14px);
    height: 2px;
    background: rgba(255,255,255,0.1);
}
.step:not(:last-child).step-done::after {
    background: rgba(72,187,120,0.5);
}
.step-circle {
    width: 28px; height: 28px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.75rem;
    font-weight: 700;
    border: 2px solid rgba(255,255,255,0.15);
    color: rgba(255,255,255,0.35);
    background: rgba(255,255,255,0.04);
    flex-shrink: 0;
    z-index: 1;
}
.step-circle.done {
    background: rgba(72,187,120,0.2);
    border-color: rgba(72,187,120,0.6);
    color: #68D391;
}
.step-circle.active {
    background: rgba(49,130,206,0.2);
    border-color: rgba(49,130,206,0.7);
    color: #63B3ED;
}
.step-text {
    font-size: 0.7rem;
    color: rgba(255,255,255,0.35);
    margin-top: 0.4rem;
    text-align: center;
    line-height: 1.3;
}
.step-text.done  { color: #68D391; }
.step-text.active { color: #63B3ED; font-weight: 600; }
/* ── Section label ────────────────────────────────────────────────── */
.section-lbl {
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.3);
    margin: 1.5rem 0 0.75rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}
.section-lbl::after {
    content: '';
    flex: 1;
    height: 1px;
    background: rgba(255,255,255,0.07);
}
/* ── Nav cards ────────────────────────────────────────────────────── */
.nav-card-icon { font-size: 1.6rem; line-height: 1; margin-bottom: 0.4rem; }
.nav-card-title {
    font-size: 0.95rem;
    font-weight: 700;
    color: rgba(255,255,255,0.9);
    margin-bottom: 0.25rem;
}
.nav-card-desc {
    font-size: 0.77rem;
    color: rgba(255,255,255,0.38);
    line-height: 1.45;
    min-height: 2.5rem;
}

/* ── Light mode overrides ──────────────────────────────────────────── */
[data-theme="light"] .stat-card {
    background: rgba(0,0,0,0.03);
    border-color: rgba(0,0,0,0.08);
}
[data-theme="light"] .stat-card .sc-num { color: rgba(0,0,0,0.85); }
[data-theme="light"] .stat-card .sc-lbl { color: rgba(0,0,0,0.4); }
[data-theme="light"] .stat-card .sc-sub { color: rgba(0,0,0,0.35); }
[data-theme="light"] .step:not(:last-child)::after { background: rgba(0,0,0,0.1); }
[data-theme="light"] .step-circle {
    border-color: rgba(0,0,0,0.15);
    color: rgba(0,0,0,0.45);
    background: rgba(0,0,0,0.03);
}
[data-theme="light"] .step-text { color: rgba(0,0,0,0.45); }
[data-theme="light"] .step-text.active { color: #2B6CB0; }
[data-theme="light"] .section-lbl { color: rgba(0,0,0,0.4); }
[data-theme="light"] .section-lbl::after { background: rgba(0,0,0,0.08); }
[data-theme="light"] .nav-card-title { color: rgba(0,0,0,0.85); }
[data-theme="light"] .nav-card-desc  { color: rgba(0,0,0,0.5); }
</style>
""", unsafe_allow_html=True)

    # ── Hero banner ───────────────────────────────────────────────────────
    today = datetime.now(timezone.utc)
    day_str  = today.strftime("%A")
    date_str = today.strftime("%d %B %Y")

    st.markdown(f"""
<div class="home-hero">
  <div class="hero-left">
    <div class="hero-flag">🇩🇪</div>
    <div>
      <div class="hero-title">German Language Learning</div>
      <div class="hero-sub">Vocabulary · Practice · Progress</div>
    </div>
  </div>
  <div class="hero-date">
    <div style="font-size:1rem;color:rgba(255,255,255,0.7);font-weight:600;">{day_str}</div>
    <div>{date_str}</div>
  </div>
</div>
""", unsafe_allow_html=True)

    # ── Live DB stats ─────────────────────────────────────────────────────
    db_path  = get_db_path()
    db_exists = Path(db_path).exists()

    vocab_count  = "—"
    attempt_count = "—"
    accuracy_str  = "—"
    last_str      = "—"
    db_ok = False

    if db_exists:
        try:
            con = storage.connect(db_path)
            vocab_count   = con.execute("SELECT COUNT(*) FROM vocab_items").fetchone()[0]
            attempt_count = con.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
            acc_row       = con.execute(
                "SELECT AVG(CASE WHEN correct THEN 1.0 ELSE 0.0 END) FROM attempts"
            ).fetchone()[0]
            last_ts       = con.execute("SELECT MAX(ts) FROM attempts").fetchone()[0]
            con.close()
            accuracy_str = f"{acc_row * 100:.0f}%" if acc_row is not None else "—"
            last_str     = last_ts[:10] if last_ts else "never"
            db_ok = True
        except Exception:
            pass

    s1, s2, s3, s4 = st.columns(4)

    def _stat_card(col, num, label, sub=""):
        col.markdown(
            f'<div class="stat-card">'
            f'<div class="sc-num">{num}</div>'
            f'<div class="sc-lbl">{label}</div>'
            f'<div class="sc-sub">{sub if sub else "&nbsp;"}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    _stat_card(s1, vocab_count,   "Vocabulary",   "words imported")
    _stat_card(s2, attempt_count, "Attempts",     "drills answered")
    _stat_card(s3, accuracy_str,  "Accuracy",     "all time")
    _stat_card(s4, last_str,      "Last Practice","")

    # ── Workflow stepper ──────────────────────────────────────────────────
    st.markdown(
        '<div class="section-lbl">Workflow</div>',
        unsafe_allow_html=True,
    )

    step_db       = db_exists
    step_vocab    = isinstance(vocab_count, int) and vocab_count > 0
    step_practice = isinstance(attempt_count, int) and attempt_count > 0

    def _step(label: str, done: bool, active: bool) -> str:
        circle_cls = "done" if done else ("active" if active else "")
        text_cls   = "done" if done else ("active" if active else "")
        icon       = "✓" if done else ("→" if active else label[0])
        return (
            f'<div class="step{" step-done" if done else ""}">'
            f'<div class="step-circle {circle_cls}">{icon}</div>'
            f'<div class="step-text {text_cls}">{label}</div>'
            f'</div>'
        )

    st.markdown(
        '<div class="stepper">'
        + _step("Initialise DB",     done=step_db,       active=not step_db)
        + _step("Import vocabulary", done=step_vocab,    active=step_db and not step_vocab)
        + _step("Practice",          done=step_practice, active=step_vocab and not step_practice)
        + _step("Review stats",      done=False,         active=step_practice)
        + '</div>',
        unsafe_allow_html=True,
    )

    # ── Nav cards ─────────────────────────────────────────────────────────
    st.markdown(
        '<div class="section-lbl">Pages</div>',
        unsafe_allow_html=True,
    )

    pages = [
        ("📝", "Vocab Export",  "Paste German words → GPT-4o enrichment → Anki TSV download.",        "pages/1_Vocab_Export.py"),
        ("📥", "Import",        "Upload a vocab file and add it to the practice database.",            "pages/2_Import.py"),
        ("🎓", "Practice",      "Interactive drill sessions — translate, articles, cloze, MCQ.",       "pages/3_Practice.py"),
        ("📊", "Stats",         "Accuracy trends, performance heatmaps, and vocabulary analytics.",    "pages/4_Stats.py"),
        ("📋", "Report",        "Worst-performing items with breakdown by drill type.",                "pages/5_Report.py"),
        ("📦", "Export Pack",   "Generate a focused study pack from your weakest-scored items.",       "pages/6_Export_Pack.py"),
    ]

    row1, row2 = pages[:3], pages[3:]

    for row in (row1, row2):
        cols = st.columns(3, gap="medium")
        for col, (icon, title, desc, path) in zip(cols, row):
            with col:
                with st.container(border=True):
                    st.markdown(
                        f'<div class="nav-card-icon">{icon}</div>'
                        f'<div class="nav-card-title">{title}</div>'
                        f'<div class="nav-card-desc">{desc}</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)
                    if st.button(f"Open {title} →", key=f"nav_{path}", use_container_width=True):
                        st.switch_page(path)

# ---------------------------------------------------------------------------
# Explicit navigation — bypasses auto-discovery of utils.py / _utils.py
# ---------------------------------------------------------------------------

pg = st.navigation([
    st.Page(home_page,                   title="Home",         icon="🏠", default=True),
    st.Page("pages/1_Vocab_Export.py",   title="Vocab Export", icon="📝"),
    st.Page("pages/2_Import.py",         title="Import",       icon="📥"),
    st.Page("pages/3_Practice.py",       title="Practice",     icon="🎓"),
    st.Page("pages/4_Stats.py",          title="Stats",        icon="📊"),
    st.Page("pages/5_Report.py",         title="Report",       icon="📋"),
    st.Page("pages/6_Export_Pack.py",    title="Export Pack",  icon="📦"),
])

pg.run()
