"""
pages/6_Export_Pack.py — Generate a focused study pack from weak items.
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from german_pipeline import storage
from ui_utils import cutoff_iso, get_db_path, list_sources, open_db

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

st.markdown("""
<style>
/* ── Page header ──────────────────────────────────────────────── */
.pack-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    margin-bottom: 1.1rem;
}
.pack-title {
    font-size: 1.5rem;
    font-weight: 800;
    color: var(--text-color);
    letter-spacing: -0.01em;
    line-height: 1.2;
}
.pack-subtitle {
    font-size: 0.8rem;
    color: color-mix(in srgb, var(--text-color) 42%, transparent);
    margin-top: 0.25rem;
    line-height: 1.45;
}

/* ── Section labels ───────────────────────────────────────────── */
.section-lbl {
    font-size: 0.64rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: color-mix(in srgb, var(--text-color) 28%, transparent);
    margin: 1.1rem 0 0.55rem;
    display: flex;
    align-items: center;
    gap: 0.55rem;
}
.section-lbl::after {
    content: '';
    flex: 1;
    height: 1px;
    background: color-mix(in srgb, var(--text-color) 6%, transparent);
}

/* ── Pack-ready banner ────────────────────────────────────────── */
.pack-banner {
    background: linear-gradient(135deg, #1a365d 0%, #2b6cb0 100%);
    border-radius: 10px;
    padding: 1.1rem 1.4rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1rem;
}
.pack-banner-left {
    display: flex;
    align-items: center;
    gap: 0.85rem;
}
.pack-banner-icon { font-size: 2rem; line-height: 1; }
.pack-banner-title {
    font-size: 1.1rem;
    font-weight: 800;
    color: #fff;
    line-height: 1.2;
}
.pack-banner-sub {
    font-size: 0.75rem;
    color: rgba(255,255,255,0.45);
    margin-top: 0.18rem;
}

/* ── Stat mini-cards ──────────────────────────────────────────── */
.mini-card {
    background: color-mix(in srgb, var(--text-color) 4%, transparent);
    border: 1px solid color-mix(in srgb, var(--text-color) 8%, transparent);
    border-radius: 8px;
    padding: 0.65rem 0.8rem;
    text-align: center;
}
.mini-card .mc-num {
    font-size: 1.5rem;
    font-weight: 800;
    color: var(--text-color);
    line-height: 1;
}
.mini-card .mc-lbl {
    font-size: 0.6rem;
    font-weight: 700;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: color-mix(in srgb, var(--text-color) 28%, transparent);
    margin-top: 0.22rem;
}

/* ── Legend pills ─────────────────────────────────────────────── */
.legend-row {
    display: flex;
    gap: 0.75rem;
    margin-bottom: 0.5rem;
    flex-wrap: wrap;
}
.legend-pill {
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    padding: 0.18rem 0.6rem;
    border-radius: 4px;
}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------

db_path = get_db_path()
if not Path(db_path).exists():
    st.title("📦 Export Pack")
    st.error("Database not found. Open ⚙️ Database settings in the sidebar and click **Initialize DB**.")
    st.stop()

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.markdown("## 📦 Export Pack")
st.markdown(
    '<p class="pack-subtitle" style="margin-top:-0.4rem;font-size:0.9rem;">'
    'Build a focused Anki study deck from your weakest vocabulary items — '
    'combines the worst-performing items (by window accuracy) with the most-missed items (all-time).'
    '</p>',
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------

with st.container(border=True):
    st.markdown('<div class="section-lbl">Pack Parameters</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    days         = c1.slider("Look-back window (days)",     min_value=7,  max_value=90, value=30, step=7)
    worst_n      = c2.slider("Worst items to include",      min_value=0,  max_value=50, value=30, step=5)
    missed_n     = c3.slider("Most-missed to include",      min_value=0,  max_value=50, value=20, step=5)
    min_attempts = c4.number_input(
        "Min attempts required",
        min_value=0, max_value=20, value=3, step=1,
        help="Items with fewer attempts than this are excluded.",
    )

    st.markdown('<div class="section-lbl">Source</div>', unsafe_allow_html=True)
    s1, s2 = st.columns([2, 3])

    con = open_db(db_path)
    try:
        sources = list_sources(con)
    finally:
        con.close()

    source_options = ["Auto (latest pipeline)", "All sources"] + sources
    source_choice  = s1.selectbox("Vocabulary source", source_options)

    alltime_scope = s2.segmented_control(
        "All-time scope for most-missed",
        options=["filtered", "global"],
        format_func=lambda v: "📌  Filtered (same source)" if v == "filtered" else "🌐  Global (all sources)",
        default="filtered",
        help=(
            "**Filtered**: most-missed items restricted to the same vocabulary source.\n\n"
            "**Global**: most-missed items drawn from all sources regardless of the source filter."
        ),
    )

# ---------------------------------------------------------------------------
# Generate button
# ---------------------------------------------------------------------------

st.markdown('<div style="height:0.1rem"></div>', unsafe_allow_html=True)
if st.button("Generate Pack →", type="primary", use_container_width=True):
    cutoff = cutoff_iso(days)

    if source_choice == "Auto (latest pipeline)":
        con = open_db(db_path)
        try:
            resolved_source = storage.get_latest_pipeline_source(con)
        finally:
            con.close()
        source, source_prefix, pipeline_only = resolved_source, None, True
    elif source_choice == "All sources":
        source, source_prefix, pipeline_only = None, None, False
    else:
        source, source_prefix, pipeline_only = source_choice, None, False

    con = open_db(db_path)
    try:
        worst = storage.query_worst_items(
            con, cutoff, worst_n,
            source=source, source_prefix=source_prefix,
            default_pipeline_only=pipeline_only,
            min_attempts=int(min_attempts),
        )

        use_global = (alltime_scope == "global")
        missed = storage.query_most_missed_alltime(
            con, top_n=missed_n,
            min_attempts=int(min_attempts),
            **(dict() if use_global else dict(
                source=source,
                source_prefix=source_prefix,
                default_pipeline_only=pipeline_only,
            )),
        )

        worst_ids  = {r["id"] for r in worst}
        missed_ids = {r["id"] for r in missed}
        all_ids    = list(worst_ids | missed_ids)

        if not all_ids:
            st.warning(
                "No items found. Try lowering **Min attempts** or widening the source filter."
            )
            con.close()
            st.stop()

        vocab_rows = storage.fetch_vocab_by_ids(con, all_ids)
    finally:
        con.close()

    worst_by_id  = {r["id"]: r for r in worst}
    missed_by_id = {r["id"]: r for r in missed}
    vocab_by_id  = {r["id"]: r for r in vocab_rows}

    worst_ordered = [r["id"] for r in worst]
    missed_only   = [r["id"] for r in missed if r["id"] not in worst_ids]
    ordered_ids   = worst_ordered + missed_only

    def _membership(vid):
        in_w, in_m = vid in worst_ids, vid in missed_ids
        if in_w and in_m:
            return "⚡  Both"
        return "📉  Worst" if in_w else "🔁  Missed"

    pack_rows = []
    for vid in ordered_ids:
        v   = vocab_by_id.get(vid, {})
        w   = worst_by_id.get(vid, {})
        m   = missed_by_id.get(vid, {})
        notes = v.get("notes") or ""
        pack_rows.append({
            "Pack":          _membership(vid),
            "German":        v.get("de_mit_artikel") or v.get("de") or "",
            "English":       v.get("en") or "",
            "Notes":         (notes[:40] + "…" if len(notes) > 40 else notes),
            "Source":        v.get("source", ""),
            "Win. accuracy": w.get("acc_window")  if vid in worst_ids  else None,
            "Win. attempts": w.get("attempts_window", "—"),
            "Times missed":  m.get("miss_count",   "—"),
            "All-time acc.": m.get("acc_alltime")  if vid in missed_ids else None,
        })

    pack_df = pd.DataFrame(pack_rows)

    # Build Anki TSV rows
    anki_rows = []
    for vid in ordered_ids:
        v   = vocab_by_id.get(vid, {})
        de  = v.get("de_mit_artikel") or v.get("de") or ""
        en  = v.get("en") or ""
        notes = v.get("notes") or ""
        notes_short = notes[:60] + "…" if len(notes) > 60 else notes
        back = f"{en} — {notes_short}" if notes_short else en
        anki_rows.append({"Front": de, "Back": back})

    anki_df = pd.DataFrame(anki_rows)

    # Persist in session state so results survive control interactions
    st.session_state["ep_pack_df"]    = pack_df
    st.session_state["ep_anki_df"]    = anki_df
    st.session_state["ep_worst_ids"]  = worst_ids
    st.session_state["ep_missed_ids"] = missed_ids
    st.session_state["ep_days"]       = days

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

if "ep_pack_df" in st.session_state:
    pack_df    = st.session_state["ep_pack_df"]
    anki_df    = st.session_state["ep_anki_df"]
    worst_ids  = st.session_state["ep_worst_ids"]
    missed_ids = st.session_state["ep_missed_ids"]
    gen_days   = st.session_state["ep_days"]
    overlap    = worst_ids & missed_ids

    # ── Banner ────────────────────────────────────────────────────────────────
    st.markdown(f"""
<div class="pack-banner">
  <div class="pack-banner-left">
    <div class="pack-banner-icon">📦</div>
    <div>
      <div class="pack-banner-title">Pack ready — {len(pack_df)} items</div>
      <div class="pack-banner-sub">
        {len(worst_ids)} worst (last {gen_days}d) · {len(missed_ids)} most-missed (all-time) · {len(overlap)} in both
      </div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

    # ── Composition cards ─────────────────────────────────────────────────────
    mc1, mc2, mc3, mc4 = st.columns(4)
    def _mc(col, num, lbl):
        col.markdown(
            f'<div class="mini-card">'
            f'<div class="mc-num">{num}</div>'
            f'<div class="mc-lbl">{lbl}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    _mc(mc1, len(pack_df),    "Total items")
    _mc(mc2, len(worst_ids),  "📉 Worst")
    _mc(mc3, len(missed_ids), "🔁 Missed")
    _mc(mc4, len(overlap),    "⚡ Both")

    # ── Composition donut ─────────────────────────────────────────────────────
    st.markdown('<div class="section-lbl">Pack Composition</div>', unsafe_allow_html=True)

    worst_only_n  = len(worst_ids  - missed_ids)
    missed_only_n = len(missed_ids - worst_ids)
    both_n        = len(overlap)

    if worst_only_n + missed_only_n + both_n > 0:
        fig_comp = go.Figure(go.Pie(
            labels=["📉 Worst only", "🔁 Missed only", "⚡ Both"],
            values=[worst_only_n, missed_only_n, both_n],
            hole=0.60,
            marker=dict(
                colors=["#FC8181", "#63B3ED", "#ECC94B"],
                line=dict(color="rgba(0,0,0,0)", width=0),
            ),
            textinfo="label+value",
            textfont=dict(size=12, color="rgba(255,255,255,0.75)"),
            hovertemplate="%{label}: <b>%{value}</b> items (%{percent})<extra></extra>",
            sort=False,
        ))
        fig_comp.add_annotation(
            text=f"<b>{len(pack_df)}</b>",
            x=0.5, y=0.58,
            font=dict(size=28, color="#fff"),
            showarrow=False,
        )
        fig_comp.add_annotation(
            text="items",
            x=0.5, y=0.42,
            font=dict(size=12, color="rgba(255,255,255,0.3)"),
            showarrow=False,
        )
        fig_comp.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="top", y=-0.02,
                xanchor="center", x=0.5,
                font=dict(size=11, color="rgba(255,255,255,0.45)"),
                bgcolor="rgba(0,0,0,0)",
            ),
            hoverlabel=dict(
                bgcolor="#1A202C",
                bordercolor="rgba(255,255,255,0.12)",
                font=dict(color="rgba(255,255,255,0.85)", size=12),
            ),
            height=260,
            margin=dict(t=8, b=8, l=8, r=8),
        )
        _, col_chart, _ = st.columns([1, 2, 1])
        with col_chart:
            st.plotly_chart(fig_comp, width="stretch")

    # ── Preview table ─────────────────────────────────────────────────────────
    st.markdown('<div class="section-lbl">Preview</div>', unsafe_allow_html=True)

    st.dataframe(
        pack_df,
        width="stretch",
        hide_index=True,
        column_config={
            "Pack":          st.column_config.TextColumn("Pack",         width="small"),
            "German":        st.column_config.TextColumn("German",       width="medium"),
            "English":       st.column_config.TextColumn("English",      width="medium"),
            "Notes":         st.column_config.TextColumn("Notes",        width="medium"),
            "Source":        st.column_config.TextColumn("Source",       width="small"),
            "Win. accuracy": st.column_config.ProgressColumn(
                "Win. accuracy",
                min_value=0, max_value=1,
                format="%.0f%%",
                help=f"Accuracy over the last {gen_days} days",
            ),
            "Win. attempts": st.column_config.NumberColumn("Win. attempts", width="small"),
            "Times missed":  st.column_config.NumberColumn("Times missed",  width="small"),
            "All-time acc.": st.column_config.ProgressColumn(
                "All-time acc.",
                min_value=0, max_value=1,
                format="%.0f%%",
                help="All-time accuracy",
            ),
        },
    )

    # ── Downloads ─────────────────────────────────────────────────────────────
    st.markdown('<div class="section-lbl">Export</div>', unsafe_allow_html=True)

    tsv_buf = io.StringIO()
    anki_df.to_csv(tsv_buf, sep="\t", index=False, header=False)

    csv_buf = io.StringIO()
    pack_df.to_csv(csv_buf, index=False)

    dl1, dl2, _, clear_col = st.columns([2, 2, 2, 1])

    dl1.download_button(
        "⬇  Download Anki TSV",
        tsv_buf.getvalue().encode("utf-8"),
        file_name="study_pack.tsv",
        mime="text/tab-separated-values",
        use_container_width=True,
        type="primary",
    )
    dl2.download_button(
        "⬇  Download full CSV",
        csv_buf.getvalue().encode("utf-8"),
        file_name="study_pack_full.csv",
        mime="text/csv",
        use_container_width=True,
    )
    if clear_col.button("✕ Clear", use_container_width=True, help="Discard this pack and reset"):
        for k in ["ep_pack_df", "ep_anki_df", "ep_worst_ids", "ep_missed_ids", "ep_days"]:
            st.session_state.pop(k, None)
        st.rerun()
