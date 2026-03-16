"""
pages/3_Practice.py — Interactive drill session.

State machine phases: "config" → "question" → "answer" → "summary"
All session state keys are prefixed with "practice_".
"""

from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from german_pipeline import drills, storage
from german_pipeline import grade as grade_module
from ui_utils import (
    MODE_ALLOWED_TYPES,
    auto_resolve_source,
    get_db_path,
    list_sources,
    open_db,
)

# ---------------------------------------------------------------------------
# Display metadata
# ---------------------------------------------------------------------------

DRILL_LABELS: dict[str, tuple[str, str]] = {
    "en_to_de":      ("Translate",  "#3182CE"),
    "article":       ("Articles",   "#805AD5"),
    "mcq_en_to_de":  ("MCQ",        "#DD6B20"),
    "mcq_article":   ("MCQ",        "#DD6B20"),
    "cloze":         ("Cloze",      "#38B2AC"),
}

MODE_META: dict[str, tuple[str, str, str]] = {
    "mixed":     ("🎲", "Mixed",       "All drill types — keeps sessions varied"),
    "translate": ("🔄", "Translate",   "English → German free-text input"),
    "articles":  ("🗂️", "Articles",    "der / die / das recall"),
    "cloze":     ("✏️", "Cloze",       "Fill in the blank in a sentence"),
    "mcq":       ("🔤", "MCQ",         "Pick the correct answer from four options"),
}

# ---------------------------------------------------------------------------
# CSS — injected once per phase render
# ---------------------------------------------------------------------------

def _inject_css() -> None:
    st.markdown("""
<style>
/* ── Page header ──────────────────────────────────────────── */
.practice-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1.4rem;
}
.practice-title {
    font-size: 1.5rem;
    font-weight: 800;
    color: rgba(255,255,255,0.92);
    letter-spacing: -0.01em;
}
.phase-badge {
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.11em;
    text-transform: uppercase;
    padding: 0.22rem 0.6rem;
    border-radius: 4px;
    background: rgba(49,130,206,0.12);
    color: #63B3ED;
    border: 1px solid rgba(49,130,206,0.22);
}

/* ── Section labels ───────────────────────────────────────── */
.section-lbl {
    font-size: 0.64rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.28);
    margin: 1.1rem 0 0.55rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}
.section-lbl::after {
    content: '';
    flex: 1;
    height: 1px;
    background: rgba(255,255,255,0.06);
}

/* ── Progress row ─────────────────────────────────────────── */
.progress-meta {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 0.78rem;
    color: rgba(255,255,255,0.35);
    margin-bottom: 0.4rem;
}
.score-pill {
    display: flex;
    gap: 0.75rem;
    font-weight: 700;
    font-size: 0.8rem;
}
.score-correct { color: #68D391; }
.score-wrong   { color: #FC8181; }

/* ── Drill badge ──────────────────────────────────────────── */
.drill-badge {
    display: inline-block;
    font-size: 0.6rem;
    font-weight: 800;
    letter-spacing: 0.13em;
    text-transform: uppercase;
    padding: 0.2rem 0.65rem;
    border-radius: 4px;
    margin-bottom: 1rem;
}

/* ── Question prompt ──────────────────────────────────────── */
.question-prompt {
    font-size: 1.35rem;
    font-weight: 700;
    color: rgba(255,255,255,0.92);
    line-height: 1.45;
    margin-bottom: 1.6rem;
    padding: 0.25rem 0;
}

/* ── MCQ radio styling ────────────────────────────────────── */
div[data-testid="stRadio"] > label {
    font-size: 0.7rem;
    font-weight: 700;
    color: rgba(255,255,255,0.35);
    letter-spacing: 0.09em;
    text-transform: uppercase;
    margin-bottom: 0.2rem;
}
div[data-testid="stRadio"] div[role="radiogroup"] label {
    display: flex;
    align-items: center;
    padding: 0.7rem 1rem;
    margin: 0.25rem 0;
    border-radius: 8px;
    border: 1px solid rgba(255,255,255,0.09);
    background: rgba(255,255,255,0.025);
    cursor: pointer;
    transition: background 0.12s, border-color 0.12s;
    font-size: 0.92rem;
    color: rgba(255,255,255,0.78);
}
div[data-testid="stRadio"] div[role="radiogroup"] label:hover {
    background: rgba(49,130,206,0.08);
    border-color: rgba(49,130,206,0.3);
}

/* ── Answer result card ───────────────────────────────────── */
.result-card {
    border-radius: 12px;
    padding: 2rem 2rem 1.75rem;
    text-align: center;
    margin-bottom: 1.25rem;
}
.result-icon   { font-size: 3rem; line-height: 1; margin-bottom: 0.55rem; }
.result-label  { font-size: 1.15rem; font-weight: 800; margin-bottom: 0.25rem; }
.result-answer { font-size: 1.65rem; font-weight: 700; margin-top: 0.3rem; }
.result-detail { font-size: 0.8rem; margin-top: 0.4rem; opacity: 0.5; }

/* ── Summary hero ─────────────────────────────────────────── */
.summary-hero {
    background: linear-gradient(135deg, #1a365d 0%, #2b6cb0 100%);
    border-radius: 12px;
    padding: 1.75rem 2.25rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1.25rem;
}
.summary-score {
    font-size: 3.2rem;
    font-weight: 900;
    color: #fff;
    line-height: 1;
}
.summary-score-sub {
    font-size: 0.7rem;
    color: rgba(255,255,255,0.4);
    letter-spacing: 0.07em;
    text-transform: uppercase;
    margin-top: 0.35rem;
}
.summary-pct {
    font-size: 3.2rem;
    font-weight: 900;
    line-height: 1;
    text-align: right;
}
.summary-mode-pill {
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    padding: 0.2rem 0.6rem;
    border-radius: 4px;
    background: rgba(255,255,255,0.12);
    color: rgba(255,255,255,0.65);
    display: inline-block;
    margin-top: 0.6rem;
}

/* ── Stat card (summary row) ──────────────────────────────── */
.stat-card-sm {
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 8px;
    padding: 0.8rem 1rem;
    text-align: center;
}
.stat-card-sm .sc-num {
    font-size: 1.7rem;
    font-weight: 800;
    color: #fff;
    line-height: 1;
}
.stat-card-sm .sc-lbl {
    font-size: 0.62rem;
    font-weight: 700;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.3);
    margin-top: 0.25rem;
}

/* ── Light mode overrides ─────────────────────────────────── */
[data-theme="light"] .phase-badge {
    color: #2B6CB0;
    background: rgba(49,130,206,0.08);
    border-color: rgba(49,130,206,0.25);
}
[data-theme="light"] .section-lbl { color: rgba(0,0,0,0.4); }
[data-theme="light"] .section-lbl::after { background: rgba(0,0,0,0.08); }
[data-theme="light"] .progress-meta { color: rgba(0,0,0,0.45); }
[data-theme="light"] .question-prompt { color: rgba(0,0,0,0.85); }
[data-theme="light"] div[data-testid="stRadio"] > label {
    color: rgba(0,0,0,0.45);
}
[data-theme="light"] div[data-testid="stRadio"] div[role="radiogroup"] label {
    border-color: rgba(0,0,0,0.1);
    background: rgba(0,0,0,0.02);
    color: rgba(0,0,0,0.78);
}
[data-theme="light"] div[data-testid="stRadio"] div[role="radiogroup"] label:hover {
    background: rgba(49,130,206,0.06);
    border-color: rgba(49,130,206,0.3);
}
[data-theme="light"] .stat-card-sm {
    background: rgba(0,0,0,0.03);
    border-color: rgba(0,0,0,0.08);
}
[data-theme="light"] .stat-card-sm .sc-num { color: rgba(0,0,0,0.85); }
[data-theme="light"] .stat-card-sm .sc-lbl { color: rgba(0,0,0,0.45); }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_practice() -> None:
    for key in list(st.session_state.keys()):
        if key.startswith("practice_"):
            del st.session_state[key]


def _drill_badge_html(drill_type: str) -> str:
    label, color = DRILL_LABELS.get(drill_type, ("Drill", "#718096"))
    return (
        f'<span class="drill-badge" style="'
        f'background:{color}22;color:{color};border:1px solid {color}44;">'
        f'{label}</span>'
    )


# ---------------------------------------------------------------------------
# Guard: DB must exist
# ---------------------------------------------------------------------------

db_path = get_db_path()
if not Path(db_path).exists():
    st.title("🎓 Practice")
    st.error("Database not found. Open ⚙️ Database settings in the sidebar and click **Initialize DB**.")
    st.stop()

# ---------------------------------------------------------------------------
# Phase router
# ---------------------------------------------------------------------------

phase = st.session_state.get("practice_phase", "config")
_inject_css()

# ============================================================
# PHASE: config
# ============================================================

if phase == "config":

    st.markdown("## 🎓 Practice")
    st.markdown('<div class="phase-badge" style="margin-bottom:0.75rem;display:inline-block;">Session Setup</div>', unsafe_allow_html=True)

    with st.container(border=True):
        # ── Drill mode ────────────────────────────────────────────────
        st.markdown('<div class="section-lbl">Drill Mode</div>', unsafe_allow_html=True)

        mode = st.segmented_control(
            "Drill mode",
            options=list(MODE_META.keys()),
            format_func=lambda m: f"{MODE_META[m][0]}  {MODE_META[m][1]}",
            default="mixed",
            label_visibility="collapsed",
            key="practice_cfg_mode",
        )
        if mode:
            _, _, desc = MODE_META[mode]
            st.markdown(
                f'<div style="font-size:0.78rem;color:rgba(255,255,255,0.35);'
                f'margin:-0.15rem 0 0.25rem;padding:0 0.15rem;">{desc}</div>',
                unsafe_allow_html=True,
            )

        # ── Session options ───────────────────────────────────────────
        st.markdown('<div class="section-lbl">Session Options</div>', unsafe_allow_html=True)

        con = open_db(db_path)
        try:
            sources = list_sources(con)
        finally:
            con.close()

        source_options = ["Auto (latest pipeline)", "All sources"] + sources
        col1, col2, col3 = st.columns([3, 3, 2])

        n_questions = col1.slider(
            "Number of questions",
            min_value=5, max_value=50, value=10, step=5,
        )
        source_choice = col2.selectbox("Vocabulary source", source_options)
        seed_input = col3.number_input(
            "Seed (0 = random)",
            min_value=0, max_value=999999, value=0, step=1,
            help="Set a non-zero seed for a reproducible session.",
        )

        st.markdown('<div style="height:0.25rem"></div>', unsafe_allow_html=True)

    # ── Launch button ─────────────────────────────────────────────────
    st.markdown('<div style="height:0.25rem"></div>', unsafe_allow_html=True)
    if st.button("Launch Session →", type="primary", use_container_width=True):
        con = open_db(db_path)
        try:
            if source_choice == "Auto (latest pipeline)":
                try:
                    source, source_prefix = auto_resolve_source(con, None, None)
                except ValueError as e:
                    st.error(str(e))
                    st.stop()
            elif source_choice == "All sources":
                source, source_prefix = None, None
            else:
                source, source_prefix = source_choice, None

            chosen_mode = mode or "mixed"
            is_mixed    = chosen_mode == "mixed"
            fetch_n     = n_questions if is_mixed else n_questions * 3
            seed        = int(seed_input) if seed_input != 0 else None

            items = storage.select_practice_items(
                con,
                fetch_n,
                source=source,
                source_prefix=source_prefix,
                default_pipeline_only=(
                    source is None
                    and source_prefix is None
                    and source_choice == "Auto (latest pipeline)"
                ),
                seed=seed,
            )
        finally:
            con.close()

        if not items:
            st.warning("No vocab items found for the given filter. Import some vocabulary first.")
            st.stop()

        rng          = random.Random(seed)
        allowed_types = MODE_ALLOWED_TYPES[chosen_mode]

        first_drill = first_item = None
        first_idx = 0
        for idx, item in enumerate(items):
            result = drills.pick_drill_with_pool(item, items, rng, allowed_types)
            if result is not None:
                first_drill = result
                first_item  = item
                first_idx   = idx
                break

        if first_drill is None:
            st.warning(
                f"No items eligible for mode '{chosen_mode}'. "
                "Try 'mixed' or import more vocabulary."
            )
            st.stop()

        st.session_state.update({
            "practice_phase":         "question",
            "practice_mode":          chosen_mode,
            "practice_n":             n_questions,
            "practice_items":         items,
            "practice_rng":           rng,
            "practice_allowed":       allowed_types,
            "practice_q_num":         0,
            "practice_item_idx":      first_idx,
            "practice_current_item":  first_item,
            "practice_current_drill": first_drill,
            "practice_n_correct":     0,
            "practice_attempt_log":   [],
            "practice_t_start":       time.perf_counter(),
        })
        st.rerun()


# ============================================================
# PHASE: question
# ============================================================

elif phase == "question":
    q_num     = st.session_state["practice_q_num"]
    n         = st.session_state["practice_n"]
    drill     = st.session_state["practice_current_drill"]
    n_correct = st.session_state["practice_n_correct"]
    n_wrong   = q_num - n_correct
    drill_type, prompt, gold_answer, choices, correct_idx = drill

    # ── Header ────────────────────────────────────────────────────────
    st.markdown("## 🎓 Practice")
    st.markdown(
        f'<div class="score-pill" style="margin-top:-0.75rem;margin-bottom:0.5rem;">'
        f'<span class="score-correct">✅ {n_correct}</span>'
        f'<span class="score-wrong">❌ {n_wrong}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Progress bar ──────────────────────────────────────────────────
    st.markdown(
        f'<div class="progress-meta">'
        f'<span>Question {q_num + 1} of {n}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.progress(q_num / n)

    st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)

    # ── Question card ─────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown(_drill_badge_html(drill_type), unsafe_allow_html=True)

        if drill_type == "cloze":
            st.markdown(
                '<div style="font-size:0.75rem;color:rgba(255,255,255,0.35);'
                'text-transform:uppercase;letter-spacing:0.07em;margin-bottom:0.5rem;">'
                'Fill in the blank</div>',
                unsafe_allow_html=True,
            )
        st.markdown(
            f'<div class="question-prompt">{prompt}</div>',
            unsafe_allow_html=True,
        )

        is_mcq = drill_type in ("mcq_en_to_de", "mcq_article")

        if is_mcq:
            labels          = list("ABCD"[: len(choices)])
            display_choices = [f"{lbl})  {ch}" for lbl, ch in zip(labels, choices)]
            selected = st.radio(
                "Choose your answer:",
                options=display_choices,
                index=None,
                key=f"practice_mcq_{q_num}",
            )
            can_submit = selected is not None
        else:
            user_input = st.text_input(
                "Your answer",
                key=f"practice_answer_{q_num}",
                placeholder="Type your German answer…",
                label_visibility="collapsed",
            )
            can_submit = bool(user_input.strip())

    # ── Submit ─────────────────────────────────────────────────────────
    col_submit, col_abandon = st.columns([5, 1])

    if col_submit.button(
        "Submit Answer →",
        disabled=not can_submit,
        type="primary",
        use_container_width=True,
        key=f"submit_{q_num}",
    ):
        t_end       = time.perf_counter()
        latency_ms  = int((t_end - st.session_state.get("practice_t_start", t_end)) * 1000)

        if is_mcq:
            choice_letter = selected.split(")")[0].strip()
            choice_idx    = "ABCD".index(choice_letter)
            is_correct    = choice_idx == correct_idx
            user_answer   = f"{choice_letter}: {choices[choice_idx]}"
            error_tags    = "" if is_correct else ("mcq article" if drill_type == "mcq_article" else "mcq")
            similarity    = None
        else:
            user_answer = user_input.strip()
            is_correct, error_tags, similarity = grade_module.grade(
                drill_type, gold_answer, user_answer
            )

        ts   = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        item = st.session_state["practice_current_item"]
        try:
            con = open_db(db_path)
            con.execute(
                "INSERT INTO attempts "
                "(vocab_id, drill_type, prompt, user_answer, is_correct, "
                " error_tags, latency_ms, ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item["id"], drill_type, prompt, user_answer,
                    int(is_correct), error_tags, latency_ms, ts,
                ),
            )
            con.commit()
        finally:
            con.close()

        if is_correct:
            st.session_state["practice_n_correct"] += 1

        st.session_state["practice_attempt_log"].append({
            "Q":           q_num + 1,
            "Type":        drill_type,
            "Prompt":      prompt[:60] + "…" if len(prompt) > 60 else prompt,
            "Your answer": user_answer,
            "Expected":    gold_answer,
            "Correct":     "✅" if is_correct else ("⚠️" if error_tags == "near_miss" else "❌"),
        })
        st.session_state["practice_last_result"] = {
            "is_correct":  is_correct,
            "error_tags":  error_tags,
            "similarity":  similarity,
            "user_answer": user_answer,
            "gold_answer": gold_answer,
            "drill_type":  drill_type,
            "choices":     choices,
            "correct_idx": correct_idx,
        }
        st.session_state["practice_phase"] = "answer"
        st.rerun()

    if col_abandon.button("✕ End", use_container_width=True, key=f"abandon_{q_num}",
                          help="End session and see summary"):
        st.session_state["practice_phase"] = "summary"
        st.rerun()


# ============================================================
# PHASE: answer
# ============================================================

elif phase == "answer":
    q_num = st.session_state["practice_q_num"]
    n     = st.session_state["practice_n"]
    res   = st.session_state["practice_last_result"]
    n_correct = st.session_state["practice_n_correct"]
    n_wrong   = (q_num + 1) - n_correct

    # ── Header ────────────────────────────────────────────────────────
    st.markdown("## 🎓 Practice")
    st.markdown(
        f'<div class="score-pill" style="margin-top:-0.75rem;margin-bottom:0.5rem;">'
        f'<span class="score-correct">✅ {n_correct}</span>'
        f'<span class="score-wrong">❌ {n_wrong}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f'<div class="progress-meta"><span>Question {q_num + 1} of {n}</span></div>',
        unsafe_allow_html=True,
    )
    st.progress((q_num + 1) / n)
    st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)

    # ── Result card ───────────────────────────────────────────────────
    if res["is_correct"]:
        bg     = "rgba(72,187,120,0.1)"
        border = "rgba(72,187,120,0.3)"
        icon   = "✅"
        label  = "Correct!"
        label_color = "#68D391"
    elif res["error_tags"] == "near_miss":
        bg     = "rgba(236,201,75,0.1)"
        border = "rgba(236,201,75,0.3)"
        icon   = "⚠️"
        pct    = int(res["similarity"] * 100) if res["similarity"] is not None else 0
        label  = f"Close!  ({pct}% match)"
        label_color = "#ECC94B"
    else:
        bg     = "rgba(252,129,129,0.1)"
        border = "rgba(252,129,129,0.3)"
        icon   = "❌"
        label  = "Incorrect"
        label_color = "#FC8181"

    gold_html = res["gold_answer"]

    if res["drill_type"] in ("mcq_en_to_de", "mcq_article") and not res["is_correct"]:
        ci   = res["correct_idx"]
        gold_html = f"{'ABCD'[ci]}) {res['choices'][ci]}"

    your_html = (
        f'<div class="result-detail">You answered: {res["user_answer"]}</div>'
        if not res["is_correct"] else ""
    )

    st.markdown(
        f'<div class="result-card" style="background:{bg};border:1px solid {border};">'
        f'<div class="result-icon">{icon}</div>'
        f'<div class="result-label" style="color:{label_color};">{label}</div>'
        f'<div class="result-answer" style="color:rgba(255,255,255,0.88);">{gold_html}</div>'
        f'{your_html}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Next button ───────────────────────────────────────────────────
    if st.button("Next Question →", type="primary", use_container_width=True):
        new_q_num = q_num + 1

        if new_q_num >= n:
            st.session_state["practice_q_num"] = new_q_num
            st.session_state["practice_phase"]  = "summary"
            st.rerun()
        else:
            items       = st.session_state["practice_items"]
            rng         = st.session_state["practice_rng"]
            allowed     = st.session_state["practice_allowed"]
            current_idx = st.session_state["practice_item_idx"]

            next_drill = next_item = None
            next_idx   = current_idx
            for idx in range(current_idx + 1, len(items)):
                result = drills.pick_drill_with_pool(items[idx], items, rng, allowed)
                if result is not None:
                    next_drill = result
                    next_item  = items[idx]
                    next_idx   = idx
                    break

            if next_drill is None:
                st.session_state["practice_q_num"] = new_q_num
                st.session_state["practice_phase"]  = "summary"
                st.rerun()
            else:
                st.session_state.update({
                    "practice_q_num":         new_q_num,
                    "practice_item_idx":      next_idx,
                    "practice_current_item":  next_item,
                    "practice_current_drill": next_drill,
                    "practice_t_start":       time.perf_counter(),
                    "practice_phase":         "question",
                })
                st.rerun()


# ============================================================
# PHASE: summary
# ============================================================

elif phase == "summary":
    q_num     = st.session_state["practice_q_num"]
    n_correct = st.session_state["practice_n_correct"]
    mode      = st.session_state.get("practice_mode", "mixed")
    pct       = int(n_correct / q_num * 100) if q_num else 0
    log       = st.session_state["practice_attempt_log"]
    n_wrong   = q_num - n_correct

    # Colour the accuracy %
    if pct >= 80:
        pct_color = "#68D391"
    elif pct >= 55:
        pct_color = "#ECC94B"
    else:
        pct_color = "#FC8181"

    mode_icon, mode_name, _ = MODE_META.get(mode, ("🎲", mode, ""))

    # ── Summary hero ──────────────────────────────────────────────────
    st.markdown(f"""
<div class="summary-hero">
  <div>
    <div class="summary-score">{n_correct}<span style="font-size:1.5rem;color:rgba(255,255,255,0.35);"> / {q_num}</span></div>
    <div class="summary-score-sub">Questions answered correctly</div>
    <div class="summary-mode-pill">{mode_icon} {mode_name}</div>
  </div>
  <div>
    <div class="summary-pct" style="color:{pct_color};">{pct}%</div>
    <div class="summary-score-sub" style="text-align:right;">Accuracy</div>
  </div>
</div>
""", unsafe_allow_html=True)

    # ── Metric row ────────────────────────────────────────────────────
    sm1, sm2, sm3, sm4 = st.columns(4)

    def _sm_card(col, num, lbl):
        col.markdown(
            f'<div class="stat-card-sm">'
            f'<div class="sc-num">{num}</div>'
            f'<div class="sc-lbl">{lbl}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    _sm_card(sm1, q_num,    "Total Questions")
    _sm_card(sm2, n_correct,"Correct")
    _sm_card(sm3, n_wrong,  "Incorrect")
    _sm_card(sm4, f"{pct}%","Accuracy")

    # ── Session log ───────────────────────────────────────────────────
    if log:
        st.markdown('<div class="section-lbl">Session Log</div>', unsafe_allow_html=True)
        log_df = pd.DataFrame(log)
        st.dataframe(log_df, width="stretch", hide_index=True)

        # ── Results chart ─────────────────────────────────────────────
        st.markdown('<div class="section-lbl">Results by Drill Type</div>', unsafe_allow_html=True)

        summary: dict[str, dict[str, int]] = {}
        for row in log:
            dt = row["Type"]
            if dt not in summary:
                summary[dt] = {"correct": 0, "near_miss": 0, "wrong": 0}
            if row["Correct"] == "✅":
                summary[dt]["correct"] += 1
            elif row["Correct"] == "⚠️":
                summary[dt]["near_miss"] += 1
            else:
                summary[dt]["wrong"] += 1

        types = list(summary.keys())
        fig = go.Figure(data=[
            go.Bar(
                name="Correct",
                x=types,
                y=[summary[t]["correct"]   for t in types],
                marker_color="#48BB78",
                marker_line_width=0,
            ),
            go.Bar(
                name="Near-miss",
                x=types,
                y=[summary[t]["near_miss"] for t in types],
                marker_color="#ECC94B",
                marker_line_width=0,
            ),
            go.Bar(
                name="Incorrect",
                x=types,
                y=[summary[t]["wrong"]     for t in types],
                marker_color="#FC8181",
                marker_line_width=0,
            ),
        ])
        fig.update_layout(
            barmode="stack",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="rgba(255,255,255,0.6)", size=12),
            xaxis=dict(
                gridcolor="rgba(255,255,255,0.06)",
                tickfont=dict(size=11),
            ),
            yaxis=dict(
                gridcolor="rgba(255,255,255,0.06)",
                tickfont=dict(size=11),
                title="Questions",
            ),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
                font=dict(size=11),
            ),
            height=300,
            margin=dict(l=0, r=0, t=32, b=0),
        )
        st.plotly_chart(fig, width="stretch")

    # ── Actions ───────────────────────────────────────────────────────
    st.markdown('<div style="height:0.25rem"></div>', unsafe_allow_html=True)
    col_new, col_home = st.columns(2)
    if col_new.button("↺  New Session", type="primary", use_container_width=True):
        _reset_practice()
        st.rerun()
    if col_home.button("🏠  Go to Home", use_container_width=True):
        st.switch_page("app.py")
