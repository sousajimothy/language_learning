"""
pages/1_Vocab_Export.py — Paste German words → GPT-4o enrichment → download.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Ensure project root is on sys.path so src/ is importable
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.vocab_export_core import clean_text, get_vocabulary_data
from ui_utils import get_db_path, open_db
from german_pipeline import ingest_export


# ── Shared DB import helper ───────────────────────────────────────────────────
def _do_db_import(df: "pd.DataFrame", source_label: str) -> None:
    """Upsert *df* rows into the practice DB under pipeline:<source_label>."""
    if not source_label.strip():
        st.error("Please enter a source label.")
        return
    rows = [
        {
            "de":             row.get("Deutsch", ""),
            "de_mit_artikel": row.get("Deutsch mit Artikel", ""),
            "en":             row.get("Englisch", ""),
            "af":             row.get("Afrikaans", ""),
            "notes":          row.get("Wortart / Genus / Hinweise", ""),
        }
        for _, row in df.iterrows()
    ]
    db_path = get_db_path()
    con = open_db(db_path)
    try:
        full_source = f"pipeline:{source_label.strip()}"
        inserted, updated = ingest_export.upsert_vocab_items(con, rows, full_source)
        con.commit()
    except Exception as e:
        con.close()
        st.error(f"Import failed: {e}")
        return
    finally:
        con.close()

    st.success(f"**{full_source}** saved to practice DB.")
    st.markdown(f"""
<div class="result-row">
  <div class="result-pill pill-inserted">
    <div class="rp-num">{inserted}</div>
    <div class="rp-lbl">Inserted</div>
  </div>
  <div class="result-pill pill-updated">
    <div class="rp-num">{updated}</div>
    <div class="rp-lbl">Updated</div>
  </div>
</div>
""", unsafe_allow_html=True)


# ── Page-scoped CSS ──────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Pipeline field chips ───────────────────────────────────────── */
.field-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
    margin: 0.5rem 0 0.25rem;
}
.field-chip {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    background: color-mix(in srgb, var(--text-color) 5%, transparent);
    border: 1px solid color-mix(in srgb, var(--text-color) 10%, transparent);
    border-radius: 20px;
    padding: 0.2rem 0.65rem;
    font-size: 0.75rem;
    color: color-mix(in srgb, var(--text-color) 65%, transparent);
}
.field-chip .dot {
    width: 6px; height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
}
/* ── Anki card mockup ───────────────────────────────────────────── */
.anki-card {
    border-radius: 10px;
    overflow: hidden;
    border: 1px solid color-mix(in srgb, var(--text-color) 10%, transparent);
    max-width: 420px;
    margin: 0.5rem auto;
}
.anki-front {
    background: linear-gradient(135deg, #1a365d 0%, #2c5282 100%);
    padding: 1.1rem 1.4rem 0.9rem;
    text-align: center;
}
.anki-front .af-label {
    font-size: 0.6rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.35);
    margin-bottom: 0.4rem;
}
.anki-front .af-word {
    font-size: 1.35rem;
    font-weight: 700;
    color: #fff;
}
.anki-front .af-hint {
    font-size: 0.75rem;
    color: rgba(255,255,255,0.45);
    margin-top: 0.25rem;
}
.anki-back {
    background: color-mix(in srgb, var(--text-color) 4%, transparent);
    padding: 0.8rem 1.4rem;
    text-align: center;
    border-top: 1px solid color-mix(in srgb, var(--text-color) 8%, transparent);
}
.anki-back .ab-label {
    font-size: 0.6rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: color-mix(in srgb, var(--text-color) 30%, transparent);
    margin-bottom: 0.3rem;
}
.anki-back .ab-word {
    font-size: 1.1rem;
    font-weight: 600;
    color: color-mix(in srgb, var(--text-color) 88%, transparent);
}
/* ── Download cards ─────────────────────────────────────────────── */
.dl-card {
    background: color-mix(in srgb, var(--text-color) 4%, transparent);
    border: 1px solid color-mix(in srgb, var(--text-color) 10%, transparent);
    border-radius: 8px;
    padding: 0.9rem 1rem 0.6rem;
    margin-bottom: 0.5rem;
}
.dl-card .dl-title {
    font-weight: 600;
    font-size: 0.9rem;
    color: color-mix(in srgb, var(--text-color) 85%, transparent);
    margin-bottom: 0.15rem;
}
.dl-card .dl-desc {
    font-size: 0.73rem;
    color: color-mix(in srgb, var(--text-color) 38%, transparent);
    margin-bottom: 0.65rem;
    line-height: 1.4;
}
/* ── Result metrics row ─────────────────────────────────────────── */
.result-row {
    display: flex;
    gap: 0.75rem;
    margin-top: 0.75rem;
}
.result-pill {
    flex: 1;
    border-radius: 8px;
    padding: 0.7rem 0.6rem 0.5rem;
    text-align: center;
    border: 1px solid color-mix(in srgb, var(--text-color) 6%, transparent);
}
.result-pill .rp-num {
    font-size: 1.6rem;
    font-weight: 800;
    line-height: 1;
}
.result-pill .rp-lbl {
    font-size: 0.62rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    margin-top: 0.25rem;
    opacity: 0.55;
}
.pill-inserted { background: rgba(72,187,120,0.12);  color: #68D391; }
.pill-updated  { background: rgba(246,173,85,0.12);  color: #F6AD55; }
/* ── Cached badge ───────────────────────────────────────────────── */
.cache-badge {
    display: inline-block;
    background: rgba(246,173,85,0.15);
    border: 1px solid rgba(246,173,85,0.3);
    color: #F6AD55;
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.06em;
    padding: 0.15rem 0.55rem;
    border-radius: 20px;
    vertical-align: middle;
    margin-left: 0.5rem;
}
</style>
""", unsafe_allow_html=True)

# ── Page header ──────────────────────────────────────────────────────────────
st.markdown("## 📝 Vocab Export")
st.markdown(
    '<p style="color:color-mix(in srgb, var(--text-color) 45%, transparent);margin-top:-0.4rem;font-size:0.9rem;">'
    "Paste raw German words or phrases — GPT-4o enriches each one and generates "
    "Anki-ready flashcard exports."
    "</p>",
    unsafe_allow_html=True,
)

# ── What GPT-4o generates ────────────────────────────────────────────────────
st.markdown(
    '<div class="field-row">'
    '<div class="field-chip"><span class="dot" style="background:#63B3ED"></span>Deutsch</div>'
    '<div class="field-chip"><span class="dot" style="background:#68D391"></span>Deutsch mit Artikel</div>'
    '<div class="field-chip"><span class="dot" style="background:#F6AD55"></span>Englisch</div>'
    '<div class="field-chip"><span class="dot" style="background:#FC8181"></span>Afrikaans</div>'
    '<div class="field-chip"><span class="dot" style="background:#B794F4"></span>Wortart / Genus / Hinweise</div>'
    '</div>',
    unsafe_allow_html=True,
)

st.markdown('<div style="height:0.75rem"></div>', unsafe_allow_html=True)

# ── Input area ───────────────────────────────────────────────────────────────
raw_text = st.text_area(
    "Paste German words or phrases — one per line",
    height=220,
    placeholder="die Autobahn\nschreiben\nins kalte Wasser springen\nder Kürbis\n...",
    label_visibility="visible",
)

# Word count hint
if raw_text.strip():
    phrase_count = len([l for l in raw_text.strip().splitlines() if l.strip()])
    st.markdown(
        f'<span style="font-size:0.78rem; color:color-mix(in srgb, var(--text-color) 35%, transparent);">'
        f'{phrase_count} phrase{"s" if phrase_count != 1 else ""} detected</span>',
        unsafe_allow_html=True,
    )

st.markdown('<div style="height:0.4rem"></div>', unsafe_allow_html=True)

# ── Controls row ─────────────────────────────────────────────────────────────
ctrl_left, ctrl_right = st.columns([3, 2])

process_clicked = ctrl_left.button(
    "✨  Enrich with GPT-4o",
    disabled=not raw_text.strip(),
    type="primary",
    use_container_width=True,
)

auto_import = ctrl_right.toggle(
    "Auto-import to DB after processing",
    value=False,
    help="When on, results are sent straight to the practice database once enrichment finishes.",
)

if auto_import:
    source_label_auto = st.text_input(
        "Source label",
        value="vocab_export",
        help="Stored as pipeline:<label> in the DB.",
        placeholder="e.g. session_01",
    )

# ── Processing ───────────────────────────────────────────────────────────────
if process_clicked and raw_text.strip():
    input_hash = hash(raw_text.strip())

    if st.session_state.get("export_input_hash") == input_hash:
        df = st.session_state["export_df"]
        from_cache = True
    else:
        from_cache = False
        phrases = clean_text(raw_text)

        with st.spinner(f"Calling GPT-4o for {len(phrases)} phrase(s)…"):
            try:
                vocab_list = get_vocabulary_data(phrases)
            except Exception as e:
                st.error(f"API error: {e}")
                st.stop()

        df = pd.DataFrame(vocab_list)
        df.rename(columns={
            "deutsch":             "Deutsch",
            "deutsch_mit_artikel": "Deutsch mit Artikel",
            "englisch":            "Englisch",
            "afrikaans":           "Afrikaans",
            "hinweise":            "Wortart / Genus / Hinweise",
        }, inplace=True)

        st.session_state["export_df"]         = df
        st.session_state["export_input_hash"] = input_hash

    # ── Section heading ──────────────────────────────────────────────────
    cached_badge = (
        '<span class="cache-badge">⚡ CACHED</span>' if from_cache else ""
    )
    st.markdown(
        f'<div style="height:1rem"></div>'
        f'<h3 style="margin-bottom:0.2rem">Enriched Vocabulary {cached_badge}</h3>'
        f'<p style="color:color-mix(in srgb, var(--text-color) 40%, transparent); font-size:0.83rem; margin-top:0;">'
        f'{len(df)} item{"s" if len(df) != 1 else ""} enriched</p>',
        unsafe_allow_html=True,
    )

    # ── Result tabs ──────────────────────────────────────────────────────
    tab_vocab, tab_anki, tab_export = st.tabs([
        "📋  Vocabulary table",
        "🃏  Anki card preview",
        "⬇️  Download & import",
    ])

    # ── Tab 1: Vocabulary table ──────────────────────────────────────────
    with tab_vocab:
        st.dataframe(
            df,
            width="stretch",
            hide_index=True,
            column_config={
                "Deutsch":                 st.column_config.TextColumn("Deutsch",       width="medium"),
                "Deutsch mit Artikel":     st.column_config.TextColumn("Mit Artikel",   width="medium"),
                "Englisch":                st.column_config.TextColumn("Englisch",       width="medium"),
                "Afrikaans":               st.column_config.TextColumn("Afrikaans",      width="medium"),
                "Wortart / Genus / Hinweise": st.column_config.TextColumn("Hinweise",   width="large"),
            },
        )

    # ── Tab 2: Anki card preview ─────────────────────────────────────────
    with tab_anki:
        st.markdown(
            '<p style="color:color-mix(in srgb, var(--text-color) 40%, transparent); font-size:0.82rem; margin-bottom:0.75rem;">'
            "Each card has the <strong>English meaning + grammar notes</strong> on the front "
            "and the <strong>German word with article</strong> on the back.</p>",
            unsafe_allow_html=True,
        )

        preview_idx = st.slider(
            "Preview card",
            min_value=1,
            max_value=len(df),
            value=1,
            key="anki_preview_slider",
            label_visibility="visible",
        ) - 1

        row = df.iloc[preview_idx]
        front_hint  = row.get("Wortart / Genus / Hinweise", "")
        front_en    = row.get("Englisch", "")
        front_text  = f"{front_en} — {front_hint}" if front_hint else front_en
        back_text   = row.get("Deutsch mit Artikel", row.get("Deutsch", ""))

        st.markdown(f"""
<div class="anki-card">
  <div class="anki-front">
    <div class="af-label">Front</div>
    <div class="af-word">{front_en}</div>
    <div class="af-hint">{front_hint}</div>
  </div>
  <div class="anki-back">
    <div class="ab-label">Back</div>
    <div class="ab-word">{back_text}</div>
  </div>
</div>
""", unsafe_allow_html=True)

    # ── Tab 3: Download & import ─────────────────────────────────────────
    with tab_export:
        # Build outputs
        xlsx_buf = io.BytesIO()
        df.to_excel(xlsx_buf, index=False, engine="openpyxl")
        xlsx_bytes = xlsx_buf.getvalue()

        anki_df = df[["Deutsch mit Artikel", "Englisch", "Wortart / Genus / Hinweise"]].copy()
        anki_df["Front"] = anki_df["Englisch"].fillna("") + " — " + anki_df["Wortart / Genus / Hinweise"].fillna("")
        anki_df["Back"]  = anki_df["Deutsch mit Artikel"]
        anki_export = anki_df[["Front", "Back"]]
        tsv_buf = io.StringIO()
        anki_export.to_csv(tsv_buf, sep="\t", index=False, header=False, encoding="utf-8")
        tsv_bytes = tsv_buf.getvalue().encode("utf-8")

        dl_left, dl_right = st.columns(2)

        with dl_left:
            st.markdown("""
<div class="dl-card">
  <div class="dl-title">📊 Full vocabulary XLSX</div>
  <div class="dl-desc">All 5 fields per word — Deutsch, Artikel, Englisch, Afrikaans, Hinweise. Use as a reference or re-import later.</div>
</div>""", unsafe_allow_html=True)
            st.download_button(
                label="Download XLSX",
                data=xlsx_bytes,
                file_name="vocab_export.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

        with dl_right:
            st.markdown("""
<div class="dl-card">
  <div class="dl-title">🃏 Anki import TSV</div>
  <div class="dl-desc">Two-column, headerless TSV — Front (English + notes) and Back (German with article). Ready to import into any Anki deck.</div>
</div>""", unsafe_allow_html=True)
            st.download_button(
                label="Download TSV",
                data=tsv_bytes,
                file_name="anki_vocab_export.tsv",
                mime="text/tab-separated-values",
                use_container_width=True,
            )

        # ── DB import ──────────────────────────────────────────────────
        st.markdown('<div style="height:0.75rem"></div>', unsafe_allow_html=True)
        st.markdown(
            '<div style="font-size:0.65rem; font-weight:700; letter-spacing:0.1em; '
            'text-transform:uppercase; color:color-mix(in srgb, var(--text-color) 35%, transparent); margin-bottom:0.5rem;">'
            'Import to practice database</div>',
            unsafe_allow_html=True,
        )

        db_left, db_right = st.columns([3, 2])
        source_label_manual = db_left.text_input(
            "Source label",
            value="vocab_export",
            help="Stored as pipeline:<label> in the DB.",
            placeholder="e.g. session_01",
            key="manual_db_source",
            label_visibility="collapsed",
        )
        import_btn = db_right.button(
            "Import to DB →",
            type="secondary",
            use_container_width=True,
            key="manual_db_import_btn",
        )

        if import_btn:
            _do_db_import(df, source_label_manual)

    # ── Auto-import (runs immediately after enrichment, outside tabs) ────
    if auto_import and not from_cache:
        _label = source_label_auto if "source_label_auto" in dir() else "vocab_export"
        _do_db_import(df, _label)
