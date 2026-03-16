"""
pages/2_Import.py — Upload a vocabulary file and import it into the practice DB.
"""

from __future__ import annotations

import hashlib
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from german_pipeline import ingest_export, storage
from ui_utils import get_db_path, open_db

# ── Page-scoped CSS ──────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Section divider label ──────────────────────────────────────── */
.step-label {
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.35);
    margin-bottom: 0.4rem;
}
/* ── Format chip strip ──────────────────────────────────────────── */
.fmt-strip {
    display: flex;
    gap: 0.6rem;
    margin: 0.5rem 0 1rem;
}
.fmt-chip {
    flex: 1;
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 8px;
    padding: 0.55rem 0.75rem;
    cursor: pointer;
    transition: border-color 0.15s, background 0.15s;
}
.fmt-chip.active {
    border-color: #3182CE;
    background: rgba(49,130,206,0.12);
}
.fmt-chip .chip-title {
    font-weight: 600;
    font-size: 0.85rem;
    color: rgba(255,255,255,0.9);
}
.fmt-chip .chip-desc {
    font-size: 0.72rem;
    color: rgba(255,255,255,0.42);
    margin-top: 0.15rem;
    line-height: 1.35;
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
    border: 1px solid rgba(255,255,255,0.06);
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
.pill-read     { background: rgba(255,255,255,0.05); }
.pill-inserted { background: rgba(72,187,120,0.12);  color: #68D391; }
.pill-updated  { background: rgba(246,173,85,0.12);  color: #F6AD55; }
.pill-skipped  { background: rgba(160,174,192,0.1);  color: #A0AEC0; }
/* ── Quick-import file card ─────────────────────────────────────── */
.file-card {
    display: flex;
    align-items: center;
    gap: 0.85rem;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 8px;
    padding: 0.75rem 1rem;
    margin-bottom: 0.85rem;
}
.file-card .fc-icon {
    font-size: 1.6rem;
    flex-shrink: 0;
}
.file-card .fc-name {
    font-weight: 600;
    font-size: 0.88rem;
    color: rgba(255,255,255,0.9);
    word-break: break-all;
}
.file-card .fc-meta {
    font-size: 0.72rem;
    color: rgba(255,255,255,0.38);
    margin-top: 0.1rem;
}
/* ── History badge ──────────────────────────────────────────────── */
.hbadge {
    display: inline-block;
    padding: 0.1rem 0.45rem;
    border-radius: 4px;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.04em;
}
.hbadge-pipeline { background: rgba(49,130,206,0.2); color: #63B3ED; }
.hbadge-anki     { background: rgba(72,187,120,0.2); color: #68D391; }
</style>
""", unsafe_allow_html=True)

# ── Page header ──────────────────────────────────────────────────────────────
st.markdown("## 📥 Import Vocabulary")
st.markdown(
    '<p style="color:rgba(255,255,255,0.45);margin-top:-0.4rem;font-size:0.9rem;">'
    "Add word lists to your practice database from a local file or the latest export."
    "</p>",
    unsafe_allow_html=True,
)

# ── Tab layout ───────────────────────────────────────────────────────────────
tab_upload, tab_quick, tab_history = st.tabs([
    "⬆️  Upload file",
    "⚡  Quick import",
    "🕓  Import history",
])

# ============================================================================
# TAB 1 — Upload file
# ============================================================================
with tab_upload:
    st.markdown('<div class="step-label">Step 1 — Select format</div>', unsafe_allow_html=True)

    fmt = st.radio(
        "Format",
        options=["pipeline", "anki"],
        format_func=lambda x: (
            "Pipeline  —  header row: Deutsch, Englisch, Afrikaans, Hinweise"
            if x == "pipeline"
            else "Anki  —  headerless 2-column TSV/CSV (Front, Back)"
        ),
        label_visibility="collapsed",
        horizontal=False,
        key="upload_fmt",
    )

    st.markdown(
        '<div style="height:0.6rem"></div>'
        '<div class="step-label">Step 2 — Choose a file</div>',
        unsafe_allow_html=True,
    )

    uploaded = st.file_uploader(
        "Drop your file here or click to browse",
        type=["tsv", "csv"] if fmt == "anki" else ["tsv", "csv", "xlsx"],
        label_visibility="collapsed",
        help=(
            "pipeline: .tsv, .csv or .xlsx with header row\n"
            "anki: headerless .tsv or .csv (2 columns: Front, Back)"
        ),
    )

    st.markdown(
        '<div style="height:0.6rem"></div>'
        '<div class="step-label">Step 3 — Name this batch</div>',
        unsafe_allow_html=True,
    )

    source_label = st.text_input(
        "Source label",
        placeholder="e.g.  session_01  or  teams_2026-03-15",
        label_visibility="collapsed",
        help="Stored as pipeline:<label> or anki:<label> in the DB. Used for filtering in Practice and Stats.",
        key="upload_source_label",
    )

    if source_label.strip():
        st.markdown(
            f'<span style="font-size:0.78rem;color:rgba(255,255,255,0.38);">'
            f'Will be stored as <code>{fmt}:{source_label.strip()}</code></span>',
            unsafe_allow_html=True,
        )

    st.markdown('<div style="height:0.4rem"></div>', unsafe_allow_html=True)

    import_btn = st.button(
        "Import →",
        type="primary",
        disabled=not (uploaded and source_label.strip()),
        key="upload_import_btn",
    )

    if import_btn:
        suffix = Path(uploaded.name).suffix.lower()

        if fmt == "anki" and suffix == ".xlsx":
            st.error("Anki format doesn't support .xlsx — use .tsv or .csv, or switch to pipeline.")
        else:
            with st.spinner("Parsing file…"):
                file_bytes = uploaded.read()
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                    tmp.write(file_bytes)
                    tmp_path = Path(tmp.name)

                try:
                    rows = ingest_export.read_table(tmp_path, fmt=fmt)
                except ValueError as e:
                    st.error(f"File parse error: {e}")
                    st.stop()
                finally:
                    tmp_path.unlink(missing_ok=True)

            full_source = f"{fmt}:{source_label.strip()}"
            file_hash   = hashlib.sha256(file_bytes).hexdigest()
            ts          = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

            db_path = get_db_path()
            con     = open_db(db_path)
            try:
                inserted, updated = ingest_export.upsert_vocab_items(con, rows, full_source)
                skipped = len(rows) - inserted - updated
                storage.record_import(
                    con,
                    ts=ts,
                    file_path=uploaded.name,
                    file_mtime=None,
                    file_hash=file_hash,
                    format=fmt,
                    source=full_source,
                    rows_read=len(rows),
                    inserted=inserted,
                    updated=updated,
                    skipped=skipped,
                )
            except Exception as e:
                con.close()
                st.error(f"DB error: {e}")
                st.stop()
            finally:
                con.close()

            st.success(f"**{full_source}** imported successfully.")
            st.markdown(f"""
<div class="result-row">
  <div class="result-pill pill-read">
    <div class="rp-num" style="color:rgba(255,255,255,0.85);">{len(rows)}</div>
    <div class="rp-lbl">Read</div>
  </div>
  <div class="result-pill pill-inserted">
    <div class="rp-num">{inserted}</div>
    <div class="rp-lbl">Inserted</div>
  </div>
  <div class="result-pill pill-updated">
    <div class="rp-num">{updated}</div>
    <div class="rp-lbl">Updated</div>
  </div>
  <div class="result-pill pill-skipped">
    <div class="rp-num">{skipped}</div>
    <div class="rp-lbl">Skipped</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ============================================================================
# TAB 2 — Quick import (latest output/ XLSX)
# ============================================================================
with tab_quick:
    output_dir = Path("output")
    xlsx_files = sorted(
        output_dir.glob("*_full_vocab_export.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    ) if output_dir.exists() else []

    if not xlsx_files:
        st.info(
            "No `*_full_vocab_export.xlsx` files found in `output/`. "
            "Run a Vocab Export first.",
            icon="📭",
        )
    else:
        latest = xlsx_files[0]
        mtime  = datetime.fromtimestamp(latest.stat().st_mtime).strftime("%Y-%m-%d  %H:%M")
        size_kb = latest.stat().st_size / 1024

        # File card
        st.markdown(f"""
<div class="file-card">
  <div class="fc-icon">📊</div>
  <div>
    <div class="fc-name">{latest.name}</div>
    <div class="fc-meta">Modified {mtime} &nbsp;·&nbsp; {size_kb:.1f} KB</div>
  </div>
</div>
""", unsafe_allow_html=True)

        quick_label = st.text_input(
            "Source label",
            value=latest.stem.replace("_full_vocab_export", ""),
            key="quick_label",
            help="Stored as pipeline:<label> in the DB.",
        )

        if quick_label.strip():
            st.markdown(
                f'<span style="font-size:0.78rem;color:rgba(255,255,255,0.38);">'
                f'Will be stored as <code>pipeline:{quick_label.strip()}</code></span>',
                unsafe_allow_html=True,
            )

        quick_btn = st.button(
            "Import latest file →",
            type="primary",
            disabled=not quick_label.strip(),
            key="quick_import_btn",
        )

        if other_count := len(xlsx_files) - 1:
            with st.expander(f"Browse {other_count} older file{'s' if other_count > 1 else ''}"):
                for f in xlsx_files[1:]:
                    mtime_other = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                    st.markdown(
                        f'<span style="font-size:0.82rem; color:rgba(255,255,255,0.6);">'
                        f'📄 {f.name}</span>'
                        f'<span style="font-size:0.72rem; color:rgba(255,255,255,0.3);"> — {mtime_other}</span>',
                        unsafe_allow_html=True,
                    )

        if quick_btn:
            with st.spinner(f"Importing {latest.name}…"):
                try:
                    rows = ingest_export.read_table(latest, fmt="pipeline")
                except ValueError as e:
                    st.error(f"File parse error: {e}")
                    st.stop()

                full_source = f"pipeline:{quick_label.strip()}"
                file_hash   = hashlib.sha256(latest.read_bytes()).hexdigest()
                ts          = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

                db_path = get_db_path()
                con     = open_db(db_path)
                try:
                    inserted, updated = ingest_export.upsert_vocab_items(con, rows, full_source)
                    skipped = len(rows) - inserted - updated
                    storage.record_import(
                        con,
                        ts=ts,
                        file_path=str(latest),
                        file_mtime=latest.stat().st_mtime,
                        file_hash=file_hash,
                        format="pipeline",
                        source=full_source,
                        rows_read=len(rows),
                        inserted=inserted,
                        updated=updated,
                        skipped=skipped,
                    )
                except Exception as e:
                    con.close()
                    st.error(f"DB error: {e}")
                    st.stop()
                finally:
                    con.close()

            st.success(f"**{full_source}** imported successfully.")
            st.markdown(f"""
<div class="result-row">
  <div class="result-pill pill-read">
    <div class="rp-num" style="color:rgba(255,255,255,0.85);">{len(rows)}</div>
    <div class="rp-lbl">Read</div>
  </div>
  <div class="result-pill pill-inserted">
    <div class="rp-num">{inserted}</div>
    <div class="rp-lbl">Inserted</div>
  </div>
  <div class="result-pill pill-updated">
    <div class="rp-num">{updated}</div>
    <div class="rp-lbl">Updated</div>
  </div>
  <div class="result-pill pill-skipped">
    <div class="rp-num">{skipped}</div>
    <div class="rp-lbl">Skipped</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ============================================================================
# TAB 3 — Import history
# ============================================================================
with tab_history:
    db_path = get_db_path()

    if not Path(db_path).exists():
        st.info("DB not found. Initialise it first via the Database settings panel.", icon="💾")
    else:
        try:
            con = open_db(db_path)
            rows_audit = con.execute(
                "SELECT ts, source, format, rows_read, inserted, updated, skipped, file_path "
                "FROM imports ORDER BY ts DESC LIMIT 50"
            ).fetchall()
            con.close()

            if not rows_audit:
                st.info("No imports recorded yet.", icon="📭")
            else:
                audit_df = pd.DataFrame(
                    rows_audit,
                    columns=["Timestamp", "Source", "Format",
                             "Read", "Inserted", "Updated", "Skipped", "File"],
                )
                audit_df["Timestamp"] = (
                    audit_df["Timestamp"].str[:19].str.replace("T", " ")
                )
                # Shorten file paths for display
                audit_df["File"] = audit_df["File"].apply(
                    lambda p: Path(p).name if p else "—"
                )

                st.caption(f"{len(audit_df)} import{'s' if len(audit_df) != 1 else ''} recorded (most recent first)")

                st.dataframe(
                    audit_df,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Timestamp": st.column_config.TextColumn("When", width="medium"),
                        "Source":    st.column_config.TextColumn("Source", width="large"),
                        "Format":    st.column_config.TextColumn("Format", width="small"),
                        "Read":      st.column_config.NumberColumn("Read",     format="%d", width="small"),
                        "Inserted":  st.column_config.NumberColumn("Inserted", format="%d", width="small"),
                        "Updated":   st.column_config.NumberColumn("Updated",  format="%d", width="small"),
                        "Skipped":   st.column_config.NumberColumn("Skipped",  format="%d", width="small"),
                        "File":      st.column_config.TextColumn("File", width="large"),
                    },
                )
        except Exception as e:
            st.warning(f"Could not load import history: {e}")
