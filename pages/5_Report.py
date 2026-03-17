"""
pages/5_Report.py — Worst-performing items report.
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from german_pipeline import storage
from ui_utils import (
    build_plotly_layout, cutoff_iso, fmt_rate, fmt_ts,
    get_db_path, get_plotly_colors, list_sources, open_db,
)

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

st.markdown("""
<style>
.report-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1.1rem;
}
.report-title {
    font-size: 1.5rem;
    font-weight: 800;
    color: var(--text-color);
    letter-spacing: -0.01em;
}
.filter-pill {
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.10em;
    text-transform: uppercase;
    padding: 0.22rem 0.65rem;
    border-radius: 4px;
    background: rgba(49,130,206,0.10);
    color: #3182CE;
    border: 1px solid rgba(49,130,206,0.20);
}
.section-lbl {
    font-size: 0.64rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: color-mix(in srgb, var(--text-color) 28%, transparent);
    margin: 1.5rem 0 0.65rem;
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
.stat-card {
    background: var(--secondary-background-color);
    border: 1.5px solid rgba(128,128,128,0.40);
    border-radius: 10px;
    padding: 0.85rem 1rem;
    text-align: center;
}
.stat-card .sc-num {
    font-size: 1.8rem;
    font-weight: 800;
    color: var(--text-color);
    line-height: 1;
}
.stat-card .sc-lbl {
    font-size: 0.62rem;
    font-weight: 700;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: color-mix(in srgb, var(--text-color) 30%, transparent);
    margin-top: 0.28rem;
}
.stat-card .sc-sub {
    font-size: 0.70rem;
    color: color-mix(in srgb, var(--text-color) 22%, transparent);
    margin-top: 0.12rem;
}
.export-row {
    display: flex;
    justify-content: flex-end;
    margin-top: 0.4rem;
}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------

db_path = get_db_path()
if not Path(db_path).exists():
    st.title("📋 Report")
    st.error("Database not found. Open ⚙️ Database settings in the sidebar and click **Initialize DB**.")
    st.stop()

title_slot = st.empty()   # filled with h2 heading once filter_label is known
pill_slot  = st.empty()   # filled with filter pill

# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------

with st.container(border=True):
    r1c1, r1c2, r1c3, r1c4 = st.columns([3, 2, 2, 3])

    days     = r1c1.slider("Look-back window (days)",        min_value=7,  max_value=90, value=30, step=7)
    worst_n  = r1c2.slider("Worst items",                    min_value=5,  max_value=50, value=20, step=5)
    missed_n = r1c3.slider("Most-missed (all-time)",         min_value=5,  max_value=50, value=20, step=5)

    con = open_db(db_path)
    try:
        sources = list_sources(con)
    finally:
        con.close()

    source_options = ["Auto (latest pipeline)", "All sources"] + sources
    source_choice  = r1c4.selectbox("Vocabulary source", source_options, label_visibility="visible")

cutoff = cutoff_iso(days)

# Resolve source
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

# ---------------------------------------------------------------------------
# Summary stats
# ---------------------------------------------------------------------------

con = open_db(db_path)
try:
    stats = storage.query_stats(
        con, cutoff,
        source=source, source_prefix=source_prefix,
        default_pipeline_only=pipeline_only,
    )
finally:
    con.close()

filter_label = stats.get("filter_label", source_choice)
_c = get_plotly_colors()   # theme-aware colour palette for all charts this render

# ── Page header — fills the placeholders reserved at the top of the page ──────
title_slot.markdown("## 📋 Report")
pill_slot.markdown(
    f'<div style="margin-top:-0.75rem;margin-bottom:0.75rem;">'
    f'<span class="filter-pill">Last {days} days · {filter_label}</span>'
    f'</div>',
    unsafe_allow_html=True,
)

# ── Metric cards ──────────────────────────────────────────────────────────────
m1, m2, m3, m4 = st.columns(4)

def _card(col, num, lbl, sub=""):
    col.markdown(
        f'<div class="stat-card">'
        f'<div class="sc-num">{num}</div>'
        f'<div class="sc-lbl">{lbl}</div>'
        f'<div class="sc-sub">{sub if sub else "&nbsp;"}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

_card(m1, stats["vocab_count"],          "Vocabulary",   "words in source")
_card(m2, stats["attempts_count"],       "Attempts",     f"last {days} days")
_card(m3, fmt_rate(stats["accuracy"]),   "Accuracy",     "window average")
_card(m4, fmt_ts(stats["last_seen"]),    "Last Practice","")

# ---------------------------------------------------------------------------
# Section 1 — Worst items (window)
# ---------------------------------------------------------------------------

st.markdown(
    f'<div class="section-lbl">Worst {worst_n} Items — Last {days} Days</div>',
    unsafe_allow_html=True,
)

con = open_db(db_path)
try:
    worst_rows = storage.query_worst_items(
        con, cutoff, worst_n,
        source=source, source_prefix=source_prefix,
        default_pipeline_only=pipeline_only,
    )
finally:
    con.close()

if worst_rows:
    worst_df = pd.DataFrame(worst_rows)

    # ── Horizontal bar chart ──────────────────────────────────────────────────
    chart_df = worst_df.sort_values("acc_window", ascending=True).head(15)
    labels   = chart_df["de_display"].fillna(chart_df["en"]).str[:28]
    accs     = (chart_df["acc_window"] * 100).round(0)
    colours  = [
        "#FC8181" if a < 40 else ("#ECC94B" if a < 70 else "#48BB78")
        for a in accs
    ]

    fig = go.Figure(go.Bar(
        x=accs,
        y=labels,
        orientation="h",
        marker=dict(color=colours, line=dict(width=0)),
        text=[f"{a:.0f}%" for a in accs],
        textposition="outside",
        textfont=dict(size=11),
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Accuracy: %{x:.0f}%<br>"
            "Attempts: %{customdata}<extra></extra>"
        ),
        customdata=chart_df["attempts_window"],
    ))
    fig.update_layout(**build_plotly_layout(_c,
        xaxis=dict(range=[0, 118], ticksuffix="%", zeroline=False),
        yaxis=dict(autorange="reversed", showgrid=False, zeroline=False),
        bargap=0.28,
        height=max(220, len(chart_df) * 28),
        margin=dict(r=52, t=8, b=4),
    ))
    st.plotly_chart(fig, width="stretch", theme=None)

    # ── Table ─────────────────────────────────────────────────────────────────
    tbl = worst_df.rename(columns={
        "de_display":       "German",
        "en":               "English",
        "acc_window":       "Accuracy",
        "attempts_window":  "Attempts",
        "near_miss_window": "Near-miss",
        "last_seen":        "Last seen",
    }).copy()
    tbl["Last seen"] = tbl["Last seen"].apply(lambda x: x[:10] if x else "—")

    st.dataframe(
        tbl[["German", "English", "Accuracy", "Attempts", "Near-miss", "Last seen"]],
        width="stretch",
        hide_index=True,
        column_config={
            "Accuracy": st.column_config.ProgressColumn(
                "Accuracy",
                min_value=0,
                max_value=1,
                format="%.0f%%",
                help="Window accuracy rate",
            ),
            "German":    st.column_config.TextColumn("German",    width="medium"),
            "English":   st.column_config.TextColumn("English",   width="medium"),
            "Last seen": st.column_config.TextColumn("Last seen", width="small"),
        },
    )

    # ── Export ────────────────────────────────────────────────────────────────
    csv_buf = io.StringIO()
    tbl.to_csv(csv_buf, index=False)
    col_exp, _ = st.columns([1, 3])
    col_exp.download_button(
        "⬇  Export as CSV",
        csv_buf.getvalue().encode("utf-8"),
        file_name=f"worst_items_{days}d.csv",
        mime="text/csv",
        use_container_width=True,
    )
else:
    st.info("No items with practice data in the selected window.")

# ---------------------------------------------------------------------------
# Section 2 — Most missed (all-time)
# ---------------------------------------------------------------------------

st.markdown(
    f'<div class="section-lbl">Most Missed — All-Time Top {missed_n}</div>',
    unsafe_allow_html=True,
)

con = open_db(db_path)
try:
    missed_rows = storage.query_most_missed_alltime(
        con, top_n=missed_n,
        source=source, source_prefix=source_prefix,
        default_pipeline_only=pipeline_only,
    )
finally:
    con.close()

if missed_rows:
    missed_df = pd.DataFrame(missed_rows).rename(columns={
        "de_display":     "German",
        "en":             "English",
        "miss_count":     "Times missed",
        "total_attempts": "Total attempts",
        "acc_alltime":    "All-time accuracy",
    })

    # ── Scatter: missed count vs all-time accuracy ────────────────────────────
    scatter_df = missed_df.copy()
    scatter_df["label"] = scatter_df["German"].fillna(scatter_df["English"]).str[:24]
    scatter_df["color"] = scatter_df["All-time accuracy"].apply(
        lambda a: "#FC8181" if a < 0.4 else ("#ECC94B" if a < 0.7 else "#48BB78")
    )

    fig_scatter = go.Figure(go.Scatter(
        x=scatter_df["All-time accuracy"] * 100,
        y=scatter_df["Times missed"],
        mode="markers+text",
        text=scatter_df["label"],
        textposition="top center",
        textfont=dict(size=9),
        marker=dict(
            color=scatter_df["color"].tolist(),
            size=scatter_df["Total attempts"].apply(lambda n: max(8, min(n * 1.5, 24))).tolist(),
            opacity=0.8,
            line=dict(color="rgba(0,0,0,0.3)", width=1),
        ),
        hovertemplate=(
            "<b>%{text}</b><br>"
            "All-time accuracy: %{x:.0f}%<br>"
            "Times missed: %{y}<extra></extra>"
        ),
        customdata=scatter_df["Total attempts"],
        showlegend=False,
    ))
    fig_scatter.add_vline(
        x=70,
        line=dict(color="rgba(72,187,120,0.25)", dash="dot", width=1.5),
        annotation_text="70% target",
        annotation_position="top right",
        annotation_font=dict(size=10, color="rgba(72,187,120,0.5)"),
    )
    fig_scatter.update_layout(**build_plotly_layout(_c,
        xaxis=dict(title="All-time accuracy", ticksuffix="%", range=[-2, 105], zeroline=False),
        yaxis=dict(title="Times missed", zeroline=False),
        height=320,
        margin=dict(l=4, r=4, t=8, b=4),
    ))
    st.plotly_chart(fig_scatter, width="stretch", theme=None)
    st.markdown(
        '<div style="font-size:0.7rem;color:color-mix(in srgb, var(--text-color) 22%, transparent);margin-top:-0.5rem;margin-bottom:0.75rem;">'
        'Bubble size ∝ total attempts. Words in the top-left corner are both frequently missed '
        'and have low accuracy — highest priority for review.</div>',
        unsafe_allow_html=True,
    )

    # ── Table ─────────────────────────────────────────────────────────────────
    st.dataframe(
        missed_df[["German", "English", "Times missed", "Total attempts", "All-time accuracy"]],
        width="stretch",
        hide_index=True,
        column_config={
            "All-time accuracy": st.column_config.ProgressColumn(
                "All-time accuracy",
                min_value=0,
                max_value=1,
                format="%.0f%%",
            ),
            "German":         st.column_config.TextColumn("German",         width="medium"),
            "English":        st.column_config.TextColumn("English",        width="medium"),
            "Times missed":   st.column_config.NumberColumn("Times missed", width="small"),
            "Total attempts": st.column_config.NumberColumn("Attempts",     width="small"),
        },
    )

    # ── Export ────────────────────────────────────────────────────────────────
    csv_buf2 = io.StringIO()
    missed_df.to_csv(csv_buf2, index=False)
    col_exp2, _ = st.columns([1, 3])
    col_exp2.download_button(
        "⬇  Export as CSV",
        csv_buf2.getvalue().encode("utf-8"),
        file_name="most_missed_alltime.csv",
        mime="text/csv",
        use_container_width=True,
    )
else:
    st.info("No items with enough practice data yet (minimum 3 attempts required).")
