"""
pages/4_Stats.py — Practice performance statistics.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from german_pipeline import storage
from ui_utils import cutoff_iso, fmt_rate, fmt_ts, get_db_path, list_sources, open_db

# ---------------------------------------------------------------------------
# Colour palette & shared chart layout
# ---------------------------------------------------------------------------

C_BLUE   = "#3182CE"
C_LBLUE  = "#63B3ED"
C_GREEN  = "#48BB78"
C_AMBER  = "#ECC94B"
C_RED    = "#FC8181"
C_PURPLE = "#B794F4"
C_TEAL   = "#38B2AC"
_BASE_LAYOUT = dict(
    # Structural / non-colour settings only.
    # All colours (font, axes, grids, legend) are intentionally omitted so
    # Streamlit's theme="streamlit" engine can own them and adapt to the
    # user's active light/dark theme without any Python-side interference.
    xaxis=dict(zeroline=False),
    yaxis=dict(zeroline=False),
    legend=dict(
        orientation="h",
        yanchor="bottom", y=1.02,
        xanchor="right", x=1,
        bgcolor="rgba(0,0,0,0)",
        borderwidth=0,
    ),
    margin=dict(l=4, r=4, t=36, b=4),
    hoverlabel=dict(
        bgcolor="#1A202C",
        bordercolor="rgba(255,255,255,0.15)",
        font=dict(color="rgba(255,255,255,0.85)", size=12),
    ),
)


def _chart_layout(**overrides) -> dict:
    """Merge overrides into the base layout."""
    import copy
    layout = copy.deepcopy(_BASE_LAYOUT)
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(layout.get(k), dict):
            layout[k].update(v)
        else:
            layout[k] = v
    return layout


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

def _inject_css() -> None:
    st.markdown("""
<style>
.stats-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1.1rem;
}
.stats-title {
    font-size: 1.5rem;
    font-weight: 800;
    color: var(--text-color);
    letter-spacing: -0.01em;
}
.filter-pill {
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    padding: 0.22rem 0.65rem;
    border-radius: 4px;
    background: rgba(49,130,206,0.1);
    color: #3182CE;
    border: 1px solid rgba(49,130,206,0.2);
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
    border: 1px solid color-mix(in srgb, var(--text-color) 18%, transparent);
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
    font-size: 0.7rem;
    color: color-mix(in srgb, var(--text-color) 22%, transparent);
    margin-top: 0.12rem;
}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------

db_path = get_db_path()
if not Path(db_path).exists():
    st.title("📊 Stats")
    st.error("Database not found. Open ⚙️ Database settings in the sidebar and click **Initialize DB**.")
    st.stop()

_inject_css()
title_slot = st.empty()   # filled with h2 heading once filter_label is known
pill_slot  = st.empty()   # filled with filter pill

# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------

with st.container(border=True):
    ctrl1, ctrl2 = st.columns([3, 3])
    days = ctrl1.slider(
        "Look-back window (days)",
        min_value=7, max_value=90, value=30, step=7,
    )
    con = open_db(db_path)
    try:
        sources = list_sources(con)
    finally:
        con.close()
    source_options = ["Auto (latest pipeline)", "All sources"] + sources
    source_choice  = ctrl2.selectbox("Vocabulary source", source_options)

cutoff = cutoff_iso(days)

# Resolve source filter
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

if source is not None:
    src_frag = "AND v.source = ?"
    src_params: tuple = (source,)
elif source_prefix is not None:
    src_frag = "AND v.source LIKE ?"
    src_params = (source_prefix + "%",)
elif pipeline_only:
    src_frag = "AND v.source LIKE 'pipeline:%'"
    src_params = ()
else:
    src_frag = ""
    src_params = ()

# ---------------------------------------------------------------------------
# Summary stats
# ---------------------------------------------------------------------------

con = open_db(db_path)
try:
    stats = storage.query_stats(
        con, cutoff,
        source=source,
        source_prefix=source_prefix,
        default_pipeline_only=pipeline_only,
    )
finally:
    con.close()

# Header — fills the placeholders reserved at the top of the page
filter_label = stats.get("filter_label", source_choice)
title_slot.markdown("## 📊 Stats")
pill_slot.markdown(
    f'<div style="margin-top:-0.75rem;margin-bottom:0.75rem;">'
    f'<span class="filter-pill">Last {days} days · {filter_label}</span>'
    f'</div>',
    unsafe_allow_html=True,
)

# Metric cards
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

_card(m1, stats["vocab_count"],                    "Vocabulary",    "words in source")
_card(m2, stats["attempts_count"],                 "Attempts",      f"last {days} days")
_card(m3, fmt_rate(stats["accuracy"]),             "Accuracy",      "all correct")
_card(m4, fmt_rate(stats["near_miss_rate"]),       "Near-miss",     "close answers")

st.markdown(
    f'<div style="font-size:0.72rem;color:color-mix(in srgb, var(--text-color) 22%, transparent);margin-top:0.4rem;'
    f'text-align:right;">Last practice: {fmt_ts(stats["last_seen"])}</div>',
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Chart 1 — Daily accuracy trend
# ---------------------------------------------------------------------------

st.markdown(f'<div class="section-lbl">Daily Accuracy — last {days} days</div>', unsafe_allow_html=True)

con = open_db(db_path)
try:
    rows_trend = con.execute(
        "SELECT SUBSTR(a.ts,1,10) AS day, "
        "       AVG(a.is_correct) AS accuracy, "
        "       COUNT(a.id) AS attempts "
        "FROM attempts a "
        "JOIN vocab_items v ON v.id = a.vocab_id "
        f"WHERE a.ts >= ? {src_frag} "
        "GROUP BY day ORDER BY day",
        (cutoff,) + src_params,
    ).fetchall()
finally:
    con.close()

if rows_trend:
    trend_df = pd.DataFrame(rows_trend, columns=["Day", "Accuracy", "Attempts"])
    trend_df["Rolling7"] = trend_df["Accuracy"].rolling(window=7, min_periods=1).mean()

    fig_trend = go.Figure()

    # Daily accuracy — filled area
    fig_trend.add_trace(go.Scatter(
        x=trend_df["Day"],
        y=trend_df["Accuracy"],
        fill="tozeroy",
        fillcolor="rgba(49,130,206,0.1)",
        line=dict(color="rgba(49,130,206,0.3)", width=0),
        showlegend=False,
        hoverinfo="skip",
    ))
    # Daily accuracy — dots
    fig_trend.add_trace(go.Scatter(
        x=trend_df["Day"],
        y=trend_df["Accuracy"],
        mode="markers",
        name="Daily accuracy",
        marker=dict(color=C_LBLUE, size=5, opacity=0.7),
        hovertemplate="<b>%{x}</b><br>Accuracy: %{y:.0%}<br>Attempts: %{customdata}<extra></extra>",
        customdata=trend_df["Attempts"],
    ))
    # 7-day rolling average
    fig_trend.add_trace(go.Scatter(
        x=trend_df["Day"],
        y=trend_df["Rolling7"],
        mode="lines",
        name="7-day avg",
        line=dict(color=C_BLUE, width=2.5, shape="spline", smoothing=0.8),
        hovertemplate="<b>%{x}</b><br>7-day avg: %{y:.0%}<extra></extra>",
    ))
    # 70% target
    fig_trend.add_hline(
        y=0.7,
        line=dict(color=C_AMBER, dash="dot", width=1.5),
        annotation_text="70% target",
        annotation_position="bottom right",
        annotation_font=dict(size=10, color=C_AMBER),
    )

    fig_trend.update_layout(**_chart_layout(
        yaxis=dict(tickformat=".0%", range=[0, 1.08], title="Accuracy"),
        xaxis=dict(title=""),
        height=280,
    ))
    st.plotly_chart(fig_trend, use_container_width=True, theme="streamlit")
else:
    st.info("No attempts in the selected window.")

# ---------------------------------------------------------------------------
# Chart 2 — Drill-type breakdown
# ---------------------------------------------------------------------------

st.markdown('<div class="section-lbl">Breakdown by Drill Type</div>', unsafe_allow_html=True)

con = open_db(db_path)
try:
    rows_drill = con.execute(
        "SELECT a.drill_type, "
        "       COUNT(a.id) AS attempts, "
        "       SUM(a.is_correct) AS correct, "
        "       SUM(CASE WHEN a.error_tags LIKE '%near_miss%' THEN 1 ELSE 0 END) AS near_miss "
        "FROM attempts a "
        "JOIN vocab_items v ON v.id = a.vocab_id "
        f"WHERE a.ts >= ? {src_frag} "
        "GROUP BY a.drill_type ORDER BY attempts DESC",
        (cutoff,) + src_params,
    ).fetchall()
finally:
    con.close()

if rows_drill:
    drill_df = pd.DataFrame(rows_drill, columns=["Drill type", "Attempts", "Correct", "Near-miss"])
    drill_df["Wrong"]    = drill_df["Attempts"] - drill_df["Correct"] - drill_df["Near-miss"]
    drill_df["Accuracy"] = drill_df["Correct"] / drill_df["Attempts"]
    drill_df["Acc %"]    = drill_df["Accuracy"].map(fmt_rate)

    fig_drill = go.Figure()
    for label, color, col in [
        ("Correct",   C_GREEN, "Correct"),
        ("Near-miss", C_AMBER, "Near-miss"),
        ("Incorrect", C_RED,   "Wrong"),
    ]:
        fig_drill.add_trace(go.Bar(
            name=label,
            x=drill_df["Drill type"],
            y=drill_df[col],
            marker=dict(color=color, line=dict(width=0)),
            hovertemplate=f"<b>%{{x}}</b><br>{label}: %{{y}}<extra></extra>",
        ))

    # Accuracy % as text annotation on each group total
    fig_drill.add_trace(go.Scatter(
        x=drill_df["Drill type"],
        y=drill_df["Attempts"] + 0.8,
        mode="text",
        text=drill_df["Acc %"],
        textfont=dict(size=11),
        showlegend=False,
        hoverinfo="skip",
    ))

    fig_drill.update_layout(**_chart_layout(
        barmode="stack",
        bargap=0.35,
        xaxis=dict(title=""),
        yaxis=dict(title="Questions"),
        height=280,
    ))
    st.plotly_chart(fig_drill, use_container_width=True, theme="streamlit")

    # Compact summary table
    tbl = drill_df[["Drill type", "Attempts", "Correct", "Near-miss", "Wrong", "Acc %"]].copy()
    tbl.columns = ["Drill type", "Total", "Correct", "Near-miss", "Incorrect", "Accuracy"]
    st.dataframe(tbl, width="stretch", hide_index=True)
else:
    st.info("No attempts in the selected window.")

# ---------------------------------------------------------------------------
# Chart 3 — Activity heatmap (90-day fixed window)
# ---------------------------------------------------------------------------

st.markdown('<div class="section-lbl">Practice Activity — last 90 days</div>', unsafe_allow_html=True)

con = open_db(db_path)
try:
    cutoff_90 = (
        datetime.now(timezone.utc) - timedelta(days=90)
    ).replace(microsecond=0).isoformat()
    rows_activity = con.execute(
        "SELECT SUBSTR(a.ts,1,10) AS day, COUNT(a.id) AS cnt "
        "FROM attempts a "
        "JOIN vocab_items v ON v.id = a.vocab_id "
        f"WHERE a.ts >= ? {src_frag} "
        "GROUP BY day ORDER BY day",
        (cutoff_90,) + src_params,
    ).fetchall()
finally:
    con.close()

if rows_activity:
    act_df = pd.DataFrame(rows_activity, columns=["Day", "Count"])
    act_df["Date"]    = pd.to_datetime(act_df["Day"])
    act_df["Weekday"] = act_df["Date"].dt.weekday
    act_df["Week"]    = act_df["Date"].dt.isocalendar().week.astype(int)
    act_df["Year"]    = act_df["Date"].dt.year
    act_df["Month"]   = act_df["Date"].dt.strftime("%b")

    pivot = act_df.pivot_table(
        index="Weekday", columns=["Year", "Week"],
        values="Count", aggfunc="sum", fill_value=0,
    )
    week_labels = [f"{y}-W{w:02d}" for y, w in pivot.columns]
    pivot.columns = week_labels
    pivot = pivot.reindex(range(7), fill_value=0)

    day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    fig_heat = go.Figure(go.Heatmap(
        z=pivot.values,
        x=week_labels,
        y=[day_labels[i] for i in pivot.index],
        colorscale=[
            [0.0,   "rgba(0,0,0,0)"],
            [0.001, "#0D4A6B"],
            [0.25,  "#1A6FA0"],
            [0.55,  "#2D9BC8"],
            [0.85,  "#48CAE4"],
            [1.0,   "#90E0EF"],
        ],
        zmin=0,
        showscale=False,
        hovertemplate="<b>%{x}</b><br>%{y}: <b>%{z}</b> attempts<extra></extra>",
        xgap=3,
        ygap=3,
    ))
    fig_heat.update_layout(
        xaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        yaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=11), side="left"),
        hoverlabel=dict(
            bgcolor="#1A202C",
            bordercolor="rgba(255,255,255,0.15)",
            font=dict(color="rgba(255,255,255,0.85)", size=12),
        ),
        height=180,
        margin=dict(t=8, b=8, l=40, r=8),
    )
    st.plotly_chart(fig_heat, use_container_width=True, theme="streamlit")
else:
    st.info("No practice data yet.")

# ---------------------------------------------------------------------------
# Charts 4 & 5 — Coverage donut  +  Hardest words (side by side)
# ---------------------------------------------------------------------------

st.markdown('<div class="section-lbl">Vocabulary Coverage  &  Hardest Words</div>', unsafe_allow_html=True)

col_donut, col_hard = st.columns(2, gap="large")

# ── Coverage donut ────────────────────────────────────────────────────────────

with col_donut:
    con = open_db(db_path)
    try:
        if source is not None:
            v_frag, v_params = "WHERE source = ?", (source,)
        elif source_prefix is not None:
            v_frag, v_params = "WHERE source LIKE ?", (source_prefix + "%",)
        elif pipeline_only:
            v_frag, v_params = "WHERE source LIKE 'pipeline:%'", ()
        else:
            v_frag, v_params = "", ()

        total     = (con.execute(f"SELECT COUNT(*) FROM vocab_items {v_frag}", v_params).fetchone() or [0])[0]
        practiced = (con.execute(
            "SELECT COUNT(DISTINCT a.vocab_id) FROM attempts a "
            "JOIN vocab_items v ON v.id = a.vocab_id "
            f"WHERE a.ts >= ? {src_frag}",
            (cutoff,) + src_params,
        ).fetchone() or [0])[0]
    finally:
        con.close()

    untouched    = max(total - practiced, 0)
    coverage_pct = int(practiced / total * 100) if total > 0 else 0

    if total > 0:
        # Colour the arc by coverage level
        arc_color = C_GREEN if coverage_pct >= 70 else (C_AMBER if coverage_pct >= 40 else C_RED)

        fig_donut = go.Figure(go.Pie(
            labels=["Practised", "Not yet"],
            values=[practiced, untouched],
            hole=0.68,
            marker=dict(
                colors=[arc_color, "rgba(120,120,130,0.30)"],
                line=dict(color="rgba(0,0,0,0)", width=0),
            ),
            textinfo="none",
            hovertemplate="%{label}: <b>%{value}</b> words (%{percent})<extra></extra>",
            sort=False,
            direction="clockwise",
        ))
        fig_donut.add_annotation(
            text=f"<b>{coverage_pct}%</b>",
            x=0.5, y=0.56,
            font=dict(size=26),
            showarrow=False,
        )
        fig_donut.add_annotation(
            text="covered",
            x=0.5, y=0.40,
            font=dict(size=11),
            showarrow=False,
        )
        fig_donut.add_annotation(
            text=f"{practiced} of {total} words",
            x=0.5, y=0.25,
            font=dict(size=11),
            showarrow=False,
        )
        fig_donut.update_layout(
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="top", y=-0.02,
                xanchor="center", x=0.5,
                bgcolor="rgba(0,0,0,0)",
            ),
            hoverlabel=dict(bgcolor="#1A202C", bordercolor="rgba(255,255,255,0.15)",
                            font=dict(color="rgba(255,255,255,0.85)", size=12)),
            height=280,
            margin=dict(t=8, b=8, l=8, r=8),
        )
        st.plotly_chart(fig_donut, use_container_width=True, theme="streamlit")
    else:
        st.info("No vocab items found for the selected source.")

# ── Hardest words ─────────────────────────────────────────────────────────────

with col_hard:
    con = open_db(db_path)
    try:
        hard_rows = storage.query_worst_items(
            con, cutoff, 10,
            source=source,
            source_prefix=source_prefix,
            default_pipeline_only=pipeline_only,
            min_attempts=2,
        )
    finally:
        con.close()

    if hard_rows:
        hard_df = pd.DataFrame(hard_rows).sort_values("acc_window", ascending=True)

        accs    = (hard_df["acc_window"] * 100).round(0)
        labels  = hard_df["de_display"].fillna(hard_df["en"]).str[:26]
        colours = [
            C_RED if a < 40 else (C_AMBER if a < 70 else C_GREEN)
            for a in accs
        ]

        fig_hard = go.Figure(go.Bar(
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
            customdata=hard_df["attempts_window"],
        ))
        fig_hard.update_layout(**_chart_layout(
            xaxis=dict(range=[0, 118], ticksuffix="%", title=""),
            yaxis=dict(autorange="reversed", showgrid=False, tickfont=dict(size=11)),
            bargap=0.3,
            height=280,
            margin=dict(l=4, r=48, t=8, b=4),
        ))
        st.plotly_chart(fig_hard, use_container_width=True, theme="streamlit")
    else:
        st.info("Not enough practice data yet (need ≥ 2 attempts per item).")

# ---------------------------------------------------------------------------
# Charts 6 & 7 — Accuracy distribution  +  Avg response latency
# ---------------------------------------------------------------------------

st.markdown('<div class="section-lbl">Accuracy Distribution  &  Response Speed</div>', unsafe_allow_html=True)

col_dist, col_lat = st.columns(2, gap="large")

# ── Chart 6: Accuracy distribution histogram ─────────────────────────────────

with col_dist:
    con = open_db(db_path)
    try:
        dist_rows = con.execute(
            """
            WITH per_item AS (
                SELECT a.vocab_id,
                       AVG(a.is_correct) AS acc,
                       COUNT(a.id)       AS cnt
                FROM attempts a
                JOIN vocab_items v ON v.id = a.vocab_id
                WHERE a.ts >= ? """ + src_frag + """
                GROUP BY a.vocab_id
                HAVING COUNT(a.id) >= 2
            )
            SELECT CAST(acc * 10 AS INTEGER) AS bucket, COUNT(*) AS word_count
            FROM per_item
            GROUP BY bucket
            ORDER BY bucket
            """,
            (cutoff,) + src_params,
        ).fetchall()
    finally:
        con.close()

    if dist_rows:
        dist_df = pd.DataFrame(dist_rows, columns=["bucket", "count"])
        # Fill gaps 0-10
        all_buckets = pd.DataFrame({"bucket": range(11)})
        dist_df = all_buckets.merge(dist_df, on="bucket", how="left").fillna(0)
        dist_df["label"] = dist_df["bucket"].apply(
            lambda b: "100%" if b == 10 else f"{int(b)*10}–{int(b)*10+9}%"
        )
        dist_df["color"] = dist_df["bucket"].apply(
            lambda b: C_GREEN if b >= 7 else (C_AMBER if b >= 4 else C_RED)
        )

        fig_dist = go.Figure(go.Bar(
            x=dist_df["label"],
            y=dist_df["count"],
            marker=dict(color=dist_df["color"].tolist(), line=dict(width=0)),
            hovertemplate="<b>%{x}</b><br>%{y} words<extra></extra>",
        ))
        fig_dist.update_layout(**_chart_layout(
            xaxis=dict(title="Accuracy bucket", tickangle=-30, tickfont=dict(size=10)),
            yaxis=dict(title="Words"),
            bargap=0.15,
            height=280,
        ))
        st.plotly_chart(fig_dist, use_container_width=True, theme="streamlit")
        st.markdown(
            '<div style="font-size:0.7rem;color:color-mix(in srgb, var(--text-color) 25%, transparent);margin-top:-0.5rem;">'
            'Words with ≥ 2 attempts, grouped by accuracy bucket.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.info("Not enough data yet (need ≥ 2 attempts per word).")

# ── Chart 7: Avg response latency by drill type ───────────────────────────────

with col_lat:
    con = open_db(db_path)
    try:
        lat_rows = con.execute(
            "SELECT a.drill_type, "
            "       ROUND(AVG(a.latency_ms)) AS avg_ms, "
            "       COUNT(a.id)              AS attempts "
            "FROM attempts a "
            "JOIN vocab_items v ON v.id = a.vocab_id "
            f"WHERE a.ts >= ? {src_frag} "
            "  AND a.latency_ms > 0 "
            "GROUP BY a.drill_type "
            "ORDER BY avg_ms DESC",
            (cutoff,) + src_params,
        ).fetchall()
    finally:
        con.close()

    if lat_rows:
        lat_df = pd.DataFrame(lat_rows, columns=["Drill type", "Avg ms", "Attempts"])
        lat_df["Avg s"] = (lat_df["Avg ms"] / 1000).round(1)

        # Colour by speed: fast (<5 s) green, medium (5–15 s) amber, slow (>15 s) red
        lat_df["color"] = lat_df["Avg s"].apply(
            lambda s: C_GREEN if s < 5 else (C_AMBER if s < 15 else C_RED)
        )

        fig_lat = go.Figure(go.Bar(
            x=lat_df["Avg s"],
            y=lat_df["Drill type"],
            orientation="h",
            marker=dict(color=lat_df["color"].tolist(), line=dict(width=0)),
            text=[f"{s}s" for s in lat_df["Avg s"]],
            textposition="outside",
            textfont=dict(size=11),
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Avg response: %{x}s<br>"
                "Attempts: %{customdata}<extra></extra>"
            ),
            customdata=lat_df["Attempts"],
        ))
        fig_lat.update_layout(**_chart_layout(
            xaxis=dict(title="Avg response time (seconds)", ticksuffix="s"),
            yaxis=dict(autorange="reversed", showgrid=False),
            bargap=0.3,
            height=280,
            margin=dict(l=4, r=48, t=8, b=4),
        ))
        st.plotly_chart(fig_lat, use_container_width=True, theme="streamlit")
        st.markdown(
            '<div style="font-size:0.7rem;color:color-mix(in srgb, var(--text-color) 25%, transparent);margin-top:-0.5rem;">'
            'Average time between receiving a question and submitting an answer.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.info("No latency data available yet.")
