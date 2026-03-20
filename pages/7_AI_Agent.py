"""
pages/7_AI_Agent.py — AI vocabulary assistant with GPT-4o tool calling.

Provides a chat interface where users can ask questions about their
vocabulary database.  The model calls predefined tool functions to
query the DB and composes markdown responses.

Conversation persistence: full message chain (including tool-call
round-trips) is stored in SQLite.  Only user/assistant messages with
text content are displayed in the chat UI.  Conversations auto-delete
after 5 days based on ``updated_at``.
"""

from __future__ import annotations

import base64
import html as html_lib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from openai import OpenAI

from german_pipeline import storage
from german_pipeline.agent import ChatResult, run_chat
from ui_utils import get_db_path, open_db


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

def _inject_css() -> None:
    st.markdown("""
<style>
/* ── AI Agent page styles ─────────────────────────────────
   NOTE: Streamlit does NOT expose --text-color,
   --background-color, or --secondary-background-color as
   CSS variables.  Use `currentColor` with color-mix() for
   text, and rgba() neutrals for backgrounds/borders so
   styles adapt to both Light and Dark themes.
   ─────────────────────────────────────────────────────── */

.conv-list-header {
    font-size: 0.58rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    opacity: 0.32;
    margin: 0.9rem 0 0.25rem;
    padding-left: 0.3rem;
}
.retention-note {
    font-size: 0.65rem;
    opacity: 0.32;
    margin-top: 0.6rem;
    padding: 0.35rem 0.5rem;
    border-radius: 6px;
    background: rgba(128, 128, 128, 0.06);
}

/* ── Conversation list items ─────────────────────────────────
   Compact, left-aligned, truncated single-line items with a
   subtle active indicator.  Sized smaller than nav labels to
   establish clear visual hierarchy in the sidebar.            */
[data-testid="stSidebar"] button[kind="secondary"] {
    font-size: 0.72rem;
    padding: 0.3rem 0.5rem;
    min-height: 0;
    line-height: 1.3;
    text-align: left !important;
    justify-content: flex-start !important;
    border-radius: 6px;
    border: 1px solid transparent !important;
    background: transparent !important;
    transition: background 0.12s, border-color 0.12s;
}
[data-testid="stSidebar"] button[kind="secondary"]:hover {
    background: rgba(128, 128, 128, 0.08) !important;
}
/* Active conversation — uses type=primary to differentiate.
   Override Streamlit's loud primary style to a subtle highlight. */
[data-testid="stSidebar"] button[kind="primary"] {
    font-size: 0.72rem;
    padding: 0.3rem 0.5rem;
    min-height: 0;
    line-height: 1.3;
    text-align: left !important;
    justify-content: flex-start !important;
    border-radius: 6px;
    border: 1px solid rgba(128, 128, 128, 0.15) !important;
    background: rgba(128, 128, 128, 0.1) !important;
    color: inherit !important;
    font-weight: 500;
    transition: background 0.12s;
}
[data-testid="stSidebar"] button[kind="primary"]:hover {
    background: rgba(128, 128, 128, 0.15) !important;
}
[data-testid="stSidebar"] button[kind="primary"] [data-testid="stMarkdownContainer"] {
    text-align: left !important;
}
[data-testid="stSidebar"] button[kind="primary"] [data-testid="stMarkdownContainer"] p {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    text-align: left !important;
    margin: 0;
}
/* Inner text wrapper — force left-align and truncation */
[data-testid="stSidebar"] button[kind="secondary"] [data-testid="stMarkdownContainer"] {
    text-align: left !important;
}
[data-testid="stSidebar"] button[kind="secondary"] [data-testid="stMarkdownContainer"] p {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    text-align: left !important;
    margin: 0;
}

/* Attachment preview chip */
.attach-chip {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    background: rgba(128, 128, 128, 0.1);
    border: 1px solid rgba(128, 128, 128, 0.2);
    border-radius: 8px;
    padding: 0.35rem 0.75rem;
    font-size: 0.78rem;
    opacity: 0.7;
    margin: 0.2rem 0 0.5rem;
}

/* ═══════════════════════════════════════════════════════════
   UNIFIED COMPOSER BAR
   A single stHorizontalBlock targeted via a hidden .cb-marker
   inside the first column.  All inner widget chrome is stripped;
   a shared border/radius/background makes the three columns
   read as one cohesive bar.

   Uses rgba() neutrals for theme-adaptive backgrounds/borders
   and currentColor + opacity for text.
   ═══════════════════════════════════════════════════════════ */

/* Hidden marker — truly zero-size, no layout impact.
   display:none still allows :has(.cb-marker) to match.       */
.cb-marker { display: none !important; }

/* The marker's Streamlit containers must also collapse so they
   don't introduce vertical gap inside the first column.       */
[data-testid="stHorizontalBlock"]:has(.cb-marker)
    [data-testid="stColumn"]:first-child
    [data-testid="stElementContainer"]:has(.cb-marker) {
    display: none !important;
}

/* Push composer to bottom of viewport when content is short.
   stVerticalBlock is already flex-column; min-height lets
   margin-top:auto on the bar push it down.                  */
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {
    min-height: calc(100vh - 5rem);
}

/* ── The bar shell ─────────────────────────────────────────── */
[data-testid="stHorizontalBlock"]:has(.cb-marker) {
    border: 1.5px solid rgba(128, 128, 128, 0.25);
    border-radius: 26px;
    background: rgba(128, 128, 128, 0.08);
    padding: 0.35rem 0.4rem 0.35rem 0.35rem;
    gap: 0 !important;
    align-items: center !important;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
/* Whole bar highlights when the text input has focus */
[data-testid="stHorizontalBlock"]:has(.cb-marker):focus-within {
    border-color: rgba(128, 128, 128, 0.45);
    box-shadow: 0 0 0 1px rgba(128, 128, 128, 0.1);
}

/* ── State A — empty: centered, narrower ───────────────────── */
[data-testid="stHorizontalBlock"]:has(.cb-empty) {
    max-width: 640px;
    margin-left: auto;
    margin-right: auto;
}

/* ── State B — active: FIXED to bottom of viewport ─────────── */
/* The active composer is truly fixed to the viewport bottom,
   not sticky.  It does not participate in scrolling at all.

   Layout strategy:
   1. stLayoutWrapper gets position:fixed spanning the full
      viewport width.  It IS the footer surface — a real,
      opaque, theme-aware backdrop that fully obscures the
      conversation beneath it.
   2. Inside that surface, the stHorizontalBlock (the bar)
      is max-width-constrained and centered within the
      available content lane.
   3. padding-bottom on the content area prevents the last
      messages from being hidden behind the fixed region.

   The JS snippet sets CSS vars on <html>:
     --cb-left       left edge of main content area (px)
     --cb-right      right edge gap from viewport right (px)
     --cb-footer-bg  page background at 92% opacity (theme-aware)
*/

/* Fixed full-width footer surface.
   This is a REAL surface, not a translucent overlay.
   It fully obscures text behind it using:
     • a near-opaque background color matching the page bg
     • backdrop-filter blur for the thin fade region at top
     • a short gradient at the top edge for a soft transition

   Dark mode  → dark surface (e.g. rgba(14,17,23,0.92))
   Light mode → light surface (e.g. rgba(255,255,255,0.92))
   Both set automatically via --cb-footer-bg from JS.         */
[data-testid="stLayoutWrapper"]:has(.cb-active) {
    position: fixed !important;
    bottom: 0 !important;
    left: 0 !important;
    right: 0 !important;
    z-index: 998 !important;
    padding: 1.25rem var(--cb-right, 1rem) 0.75rem var(--cb-left, 17rem) !important;
    margin: 0 !important;
    height: auto !important;
    /* Real footer surface: short transparent-to-solid fade at top,
       then fully opaque.  backdrop-filter handles the thin fade
       region so even the gradient zone doesn't leak text.       */
    background: linear-gradient(
        to bottom,
        transparent,
        var(--cb-footer-bg, rgba(128, 128, 128, 0.95)) 1.25rem
    ) !important;
    backdrop-filter: blur(12px) saturate(120%) !important;
    -webkit-backdrop-filter: blur(12px) saturate(120%) !important;
    /* Subtle top border to visually separate from content */
    border-top: 1px solid rgba(128, 128, 128, 0.08) !important;
    pointer-events: none;
}
/* Allow clicks on the bar and its controls.
   Also constrain the bar width and center it within the
   available lane for a cleaner look on wide screens.         */
[data-testid="stLayoutWrapper"]:has(.cb-active)
    [data-testid="stHorizontalBlock"] {
    pointer-events: auto;
    max-width: 44rem;
    margin-left: auto !important;
    margin-right: auto !important;
}
/* Reserve bottom space — ONLY on the page-level stVerticalBlock
   (direct child of stMainBlockContainer), NOT column-level ones. */
[data-testid="stMainBlockContainer"] >
    [data-testid="stVerticalBlock"]:has(.cb-active) {
    padding-bottom: 5.5rem;
}

/* ── Column alignment inside the bar ───────────────────────── */
/* All three columns: flex, vertically centered, no extra gap.
   Streamlit uses data-testid="stColumn" (not "column").       */
[data-testid="stHorizontalBlock"]:has(.cb-marker) > [data-testid="stColumn"] {
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    height: 38px !important;
    overflow: visible !important;
}
/* Kill the vertical gap Streamlit puts between stacked children
   inside each column — this is critical for the first column
   which has the (hidden) marker + popover stacked.            */
[data-testid="stHorizontalBlock"]:has(.cb-marker)
    [data-testid="stVerticalBlock"] {
    gap: 0 !important;
    justify-content: center !important;
    align-items: center !important;
}
/* Remove bottom padding that Streamlit injects on layout wrappers */
[data-testid="stHorizontalBlock"]:has(.cb-marker)
    [data-testid="stLayoutWrapper"] {
    padding: 0 !important;
    margin: 0 !important;
}

/* ── Text input — strip native border / background ─────────── */
[data-testid="stHorizontalBlock"]:has(.cb-marker) [data-testid="stTextInput"] {
    width: 100%;
}
[data-testid="stHorizontalBlock"]:has(.cb-marker) [data-baseweb="input"],
[data-testid="stHorizontalBlock"]:has(.cb-marker) [data-baseweb="input"] > div {
    background: transparent !important;
    border-color: transparent !important;
    box-shadow: none !important;
}
[data-testid="stHorizontalBlock"]:has(.cb-marker) input[type="text"] {
    background: transparent !important;
    caret-color: currentColor;
    height: 38px !important;
    padding: 0 0.5rem !important;
    font-size: 0.92rem !important;
}
/* Remove bottom padding on the text input element container */
[data-testid="stHorizontalBlock"]:has(.cb-marker)
    [data-testid="stElementContainer"]:has([data-testid="stTextInput"]) {
    padding: 0 !important;
    margin: 0 !important;
}

/* ── + attach trigger — borderless icon button ─────────────── */
/* Note: data-testid="stPopoverButton" is ON the <button> itself */
[data-testid="stHorizontalBlock"]:has(.cb-marker)
    [data-testid="stPopover"] {
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
}
[data-testid="stHorizontalBlock"]:has(.cb-marker)
    button[data-testid="stPopoverButton"] {
    background: none !important;
    border: none !important;
    box-shadow: none !important;
    opacity: 0.45;
    width: 38px !important;
    height: 38px !important;
    min-height: 0 !important;
    padding: 0 !important;
    font-size: 1.3rem !important;
    font-weight: 300 !important;
    line-height: 1 !important;
    border-radius: 50% !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    transition: opacity 0.12s ease, background 0.12s ease;
}
[data-testid="stHorizontalBlock"]:has(.cb-marker)
    button[data-testid="stPopoverButton"]:hover {
    opacity: 0.75 !important;
    background: rgba(128, 128, 128, 0.12) !important;
}
/* Hide the chevron / expand_more — it's a material icon span, not SVG.
   Target the chevron's parent container (last child inside the button's
   inner flex wrapper) so it collapses completely.                      */
[data-testid="stHorizontalBlock"]:has(.cb-marker)
    button[data-testid="stPopoverButton"] > div > div:last-child {
    display: none !important;
}
/* Center the + label inside the button.
   Streamlit sets margin: 0 -5px 0 0 on the inner wrapper div,
   which shifts the 38px div 2.5px right when flex-centered
   in the 38px button.  Zero it out for true centering.        */
[data-testid="stHorizontalBlock"]:has(.cb-marker)
    button[data-testid="stPopoverButton"] > div {
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    width: 100% !important;
    height: 100% !important;
    margin: 0 !important;
}

/* ── ↑ send button — themed circle, matched sizing ─────────── */
[data-testid="stHorizontalBlock"]:has(.cb-marker) button[kind="primary"] {
    border-radius: 50% !important;
    width: 38px !important;
    height: 38px !important;
    min-height: 0 !important;
    padding: 0 !important;
    font-size: 1.15rem !important;
    line-height: 1 !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
}
/* Optical fix: ↑ glyph has more visual weight at the bottom
   (shaft) than the top (arrowhead), making it appear low even
   when box-centered.  Nudge inner wrapper up 1px.            */
[data-testid="stHorizontalBlock"]:has(.cb-marker) button[kind="primary"] > div {
    transform: translateY(-1px);
}
/* Remove extra wrapper padding around the send button */
[data-testid="stHorizontalBlock"]:has(.cb-marker)
    [data-testid="stColumn"]:last-child
    [data-testid="stElementContainer"] {
    padding: 0 !important;
    margin: 0 !important;
}

/* ── Empty-state hero section ──────────────────────────────── */
.empty-hero {
    text-align: center;
    padding: 3rem 1rem 2rem;
    opacity: 0.55;
}
.empty-hero .hero-icon {
    font-size: 2rem;
    margin-bottom: 0.6rem;
    opacity: 0.6;
}
.empty-hero .hero-title {
    font-size: 1rem;
    font-weight: 600;
    opacity: 0.85;
    margin-bottom: 0.35rem;
}
.empty-hero .hero-hints {
    font-size: 0.8rem;
    line-height: 1.6;
    opacity: 0.65;
}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Guard: DB must exist
# ---------------------------------------------------------------------------

db_path = get_db_path()
if not Path(db_path).exists():
    st.title("🤖 AI Agent")
    st.error(
        "Database not found. Open ⚙\ufe0f Database settings in the "
        "sidebar and click **Initialize DB**."
    )
    st.stop()

_inject_css()

# ---------------------------------------------------------------------------
# Auto-migrate: ensure conversation tables exist
# ---------------------------------------------------------------------------

try:
    _con = open_db(db_path)
    try:
        storage.init_db(_con)
    finally:
        _con.close()
except Exception:
    pass  # non-fatal — tables may already exist

# ---------------------------------------------------------------------------
# 5-day purge (best-effort on page load)
# ---------------------------------------------------------------------------

try:
    _con = open_db(db_path)
    try:
        storage.purge_old_conversations(_con, max_age_days=5)
    finally:
        _con.close()
except Exception:
    pass

# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------

if "chat_conv_id" not in st.session_state:
    st.session_state["chat_conv_id"] = None
if "chat_messages" not in st.session_state:
    st.session_state["chat_messages"] = []
if "_upload_counter" not in st.session_state:
    st.session_state["_upload_counter"] = 0
if "_input_key_ctr" not in st.session_state:
    st.session_state["_input_key_ctr"] = 0


def _mark_send() -> None:
    """Callback shared by Enter (on_change) and Send button (on_click)."""
    st.session_state["_pending_send"] = True


# ---------------------------------------------------------------------------
# Pending-send detection — runs BEFORE any rendering so that the new
# user message + streamed response appear above the composer in the
# correct visual order.
# ---------------------------------------------------------------------------

_prompt: str | None = None
_attached_for_send: dict | None = None

if st.session_state.pop("_pending_send", False):
    _key = f"_chat_prompt_{st.session_state['_input_key_ctr']}"
    _val = (st.session_state.get(_key) or "").strip()
    if _val:
        _prompt = _val
        _attached_for_send = st.session_state.pop("_attached_image", None)
        # Advance the key so the text_input widget resets to empty
        st.session_state["_input_key_ctr"] += 1
        if _attached_for_send:
            st.session_state["_upload_counter"] += 1

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _group_conversations(convs: list[dict]) -> dict[str, list[dict]]:
    """Group conversations into Today / Yesterday / Older buckets."""
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    yesterday_str = (
        now.replace(hour=0, minute=0, second=0, microsecond=0)
    ).__class__(
        now.year, now.month, now.day, tzinfo=timezone.utc
    )
    from datetime import timedelta
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    groups: dict[str, list[dict]] = {"Today": [], "Yesterday": [], "Older": []}
    for c in convs:
        date_str = c["updated_at"][:10]
        if date_str == today_str:
            groups["Today"].append(c)
        elif date_str == yesterday_str:
            groups["Yesterday"].append(c)
        else:
            groups["Older"].append(c)
    return groups


def _load_conversation(conv_id: int) -> None:
    """Load a conversation's messages into session state."""
    con = open_db(db_path)
    try:
        msgs = storage.load_messages(con, conv_id)
    finally:
        con.close()
    st.session_state["chat_conv_id"] = conv_id
    st.session_state["chat_messages"] = msgs


def _display_messages(messages: list[dict]) -> list[dict]:
    """Filter messages to only user/assistant with text content."""
    return [
        m for m in messages
        if m["role"] in ("user", "assistant") and m.get("content")
    ]


def _generate_conversation_title(prompt: str) -> str:
    """Generate a short 3-6 word conversation title via gpt-4o-mini.

    Falls back to a truncated prompt if the API call fails.
    Uses gpt-4o-mini for cost efficiency (~0.01 cent per title).
    """
    fallback = prompt[:40].strip()
    if len(prompt) > 40:
        fallback += "…"
    try:
        import os

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return fallback
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Generate a short conversation title (3-6 words) for a "
                        "chat sidebar. The title should summarize the user's "
                        "request concisely, like a chat subject line. "
                        "Do NOT use quotes. Do NOT use full sentences. "
                        "Examples: 'B1 emotion vocabulary', 'Konjunktiv II examples', "
                        "'Image text extraction'. Reply with ONLY the title."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=20,
            temperature=0.3,
        )
        title = resp.choices[0].message.content.strip().strip('"').strip("'")
        # Safety: cap at 50 chars
        if len(title) > 50:
            title = title[:47] + "…"
        return title or fallback
    except Exception:
        return fallback


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def _export_markdown(messages: list[dict]) -> str:
    """Export visible conversation messages as markdown."""
    parts: list[str] = []
    for m in _display_messages(messages):
        role = "You" if m["role"] == "user" else "Assistant"
        parts.append(f"### {role}\n\n{m['content']}\n\n---")
    return "\n\n".join(parts)


def _export_plaintext(messages: list[dict]) -> str:
    """Export visible conversation messages as plain text."""
    parts: list[str] = []
    for m in _display_messages(messages):
        role = "You" if m["role"] == "user" else "Assistant"
        parts.append(f"[{role}]: {m['content']}")
    return "\n\n".join(parts)


def _export_html(messages: list[dict]) -> str:
    """Export visible conversation messages as styled HTML."""
    from jinja2 import Template

    tmpl = Template(
        "<!DOCTYPE html>\n"
        "<html>\n<head>\n"
        '<meta charset="utf-8">\n'
        "<title>Conversation Export</title>\n"
        "<style>\n"
        "body { font-family: -apple-system, BlinkMacSystemFont, "
        "'Segoe UI', sans-serif; max-width: 700px; margin: 2rem auto; "
        "padding: 0 1rem; background: #f7f7f8; color: #1a1a1a; }\n"
        ".msg { margin: 1rem 0; padding: 1rem 1.2rem; "
        "border-radius: 12px; }\n"
        ".user { background: #e3f2fd; "
        "border-left: 4px solid #3182CE; }\n"
        ".assistant { background: #fff; "
        "border-left: 4px solid #48BB78; "
        "box-shadow: 0 1px 3px rgba(0,0,0,0.08); }\n"
        ".role { font-size: 0.75rem; font-weight: 700; "
        "text-transform: uppercase; letter-spacing: 0.05em; "
        "color: #666; margin-bottom: 0.4rem; }\n"
        ".content { line-height: 1.6; white-space: pre-wrap; }\n"
        "</style>\n</head>\n<body>\n"
        "<h1>Conversation Export</h1>\n"
        "{% for msg in messages %}\n"
        '<div class="msg {{ msg.role }}">\n'
        '  <div class="role">'
        '{{ "You" if msg.role == "user" else "Assistant" }}'
        "</div>\n"
        '  <div class="content">{{ msg.content | e }}</div>\n'
        "</div>\n"
        "{% endfor %}\n"
        "</body>\n</html>",
        autoescape=False,
    )
    return tmpl.render(messages=_display_messages(messages))


def _build_openai_messages(db_messages: list[dict]) -> list[dict]:
    """Convert stored DB messages to OpenAI API format."""
    openai_msgs: list[dict] = []
    for m in db_messages:
        msg: dict = {"role": m["role"]}
        if m["content"] is not None:
            msg["content"] = m["content"]
        if m["tool_calls_json"]:
            msg["tool_calls"] = json.loads(m["tool_calls_json"])
        if m["tool_call_id"]:
            msg["tool_call_id"] = m["tool_call_id"]
        # Tool messages require content field
        if m["role"] == "tool" and "content" not in msg:
            msg["content"] = ""
        openai_msgs.append(msg)
    return openai_msgs


# ---------------------------------------------------------------------------
# Message rendering helpers — copy buttons & code block extraction
# ---------------------------------------------------------------------------

_CODE_FENCE_RE = re.compile(r"(```[^\n]*\n.*?\n```)", re.DOTALL)

#: Max image upload size in megabytes.
_MAX_UPLOAD_MB = 5
_ACCEPTED_IMAGE_TYPES = ["jpg", "jpeg", "png", "gif", "webp"]


def _render_message_content(content: str) -> None:
    """Render markdown with fenced code blocks extracted to ``st.code()``.

    ``st.code()`` provides Streamlit's built-in copy button on each block,
    while the surrounding prose is rendered as normal markdown.
    """
    parts = _CODE_FENCE_RE.split(content)
    for part in parts:
        stripped = part.strip()
        if not stripped:
            continue
        if stripped.startswith("```"):
            try:
                first_nl = stripped.index("\n")
            except ValueError:
                st.markdown(stripped)
                continue
            lang = stripped[3:first_nl].strip() or None
            body = stripped[first_nl + 1:]
            if body.endswith("\n```"):
                body = body[:-4]
            elif body.endswith("```"):
                body = body[:-3]
            st.code(body, language=lang)
        else:
            st.markdown(stripped)


def _copy_button(text: str, key: str) -> None:
    """Render a compact icon-only copy-to-clipboard button.

    Uses inline SVG icons (clipboard → checkmark) for a modern,
    compact feel.  The checkmark state persists for 1.5 s, then
    automatically reverts.  Each button instance is independent.
    """
    safe_text = html_lib.escape(text)
    components.html(
        f"""
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ background: transparent; }}
            .cpb {{
                all: unset;
                cursor: pointer;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                width: 28px;
                height: 28px;
                border-radius: 6px;
                transition: background 0.15s;
            }}
            .cpb:hover {{
                background: rgba(128,128,128,0.1);
            }}
            .cpb svg {{
                width: 16px;
                height: 16px;
                fill: none;
                stroke-width: 2;
                stroke-linecap: round;
                stroke-linejoin: round;
                /* Light mode default: dark gray icon */
                stroke: rgba(80, 80, 80, 0.45);
                transition: stroke 0.15s;
            }}
            .cpb:hover svg {{
                stroke: rgba(80, 80, 80, 0.75);
            }}
            /* Dark mode: explicit light icon color */
            .cpb.dark svg {{
                stroke: rgba(200, 200, 210, 0.6);
            }}
            .cpb.dark:hover svg {{
                stroke: rgba(200, 200, 210, 0.85);
            }}
            /* Copied state: green check in both themes */
            .cpb.copied svg {{ stroke: #22c55e !important; }}
        </style>
        <textarea id="ct"
                  style="position:fixed;opacity:0;pointer-events:none;left:-9999px"
        >{safe_text}</textarea>
        <button class="cpb" aria-label="Copy to clipboard" onclick="
            var t=document.getElementById('ct');
            t.style.cssText='position:fixed;left:0;top:0;opacity:0.01';
            t.select(); t.setSelectionRange(0,999999);
            document.execCommand('copy');
            t.style.cssText='position:fixed;opacity:0;pointer-events:none;left:-9999px';
            var b=this;
            b.classList.add('copied');
            b.innerHTML='<svg viewBox=&quot;0 0 24 24&quot;><polyline points=&quot;20 6 9 17 4 12&quot;/></svg>';
            setTimeout(function(){{
                b.classList.remove('copied');
                b.innerHTML='<svg viewBox=&quot;0 0 24 24&quot;><rect x=&quot;9&quot; y=&quot;9&quot; width=&quot;13&quot; height=&quot;13&quot; rx=&quot;2&quot;/><path d=&quot;M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1&quot;/></svg>';
            }}, 1500);
        "><svg viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button>
        <script>(function(){{
            var btn=document.querySelector('.cpb');
            if(!btn) return;
            function detect(){{
                try {{
                    var app=parent.document.querySelector('[data-testid="stApp"]');
                    if(!app) return;
                    var bg=parent.getComputedStyle(app).backgroundColor;
                    var m=bg.match(/\d+/g);
                    if(m){{
                        if((0.299*m[0]+0.587*m[1]+0.114*m[2])<128)
                            btn.classList.add('dark');
                        else
                            btn.classList.remove('dark');
                    }}
                }} catch(e){{}}
            }}
            /* Run once immediately, then install a permanent
               observer on stApp so theme switches are caught
               even after the initial load window.  Guard with
               a shared list so each iframe can be notified.    */
            detect();
            try {{
                if(!parent.__cpbCallbacks) parent.__cpbCallbacks=[];
                parent.__cpbCallbacks.push(detect);
                if(!parent.__cpbObserver) {{
                    var app=parent.document.querySelector('[data-testid="stApp"]');
                    if(app) {{
                        parent.__cpbObserver=new MutationObserver(function(){{
                            (parent.__cpbCallbacks||[]).forEach(function(fn){{
                                try {{ fn(); }} catch(e){{}}
                            }});
                        }});
                        parent.__cpbObserver.observe(app,{{
                            attributes:true,
                            attributeFilter:['class','style']
                        }});
                    }}
                }}
            }} catch(e){{}}
        }})();</script>
        """,
        height=28,
    )


# ---------------------------------------------------------------------------
# Sidebar — conversation list + controls
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("---")
    st.markdown("##### 💬 Conversations")

    if st.button("➕ New conversation", use_container_width=True, key="chat_new"):
        st.session_state["chat_conv_id"] = None
        st.session_state["chat_messages"] = []
        st.rerun()

    # Load conversation list
    con = open_db(db_path)
    try:
        conversations = storage.list_conversations(con, max_age_days=30)
    finally:
        con.close()

    if conversations:
        groups = _group_conversations(conversations)
        for label, convs in groups.items():
            if not convs:
                continue
            st.markdown(
                f'<div class="conv-list-header">{label}</div>',
                unsafe_allow_html=True,
            )
            for conv in convs:
                title = conv["title"] or "Untitled"
                is_active = conv["id"] == st.session_state.get("chat_conv_id")
                btn_label = f"▸ {title}" if is_active else title
                btn_type = "primary" if is_active else "secondary"
                if st.button(
                    btn_label,
                    key=f"conv_{conv['id']}",
                    use_container_width=True,
                    type=btn_type,
                ):
                    _load_conversation(conv["id"])
                    st.rerun()

    # Delete button
    if st.session_state["chat_conv_id"] is not None:
        st.markdown("")
        if st.button(
            "🗑 Delete conversation",
            use_container_width=True,
            key="chat_delete",
        ):
            con = open_db(db_path)
            try:
                storage.delete_conversation(
                    con, st.session_state["chat_conv_id"]
                )
            finally:
                con.close()
            st.session_state["chat_conv_id"] = None
            st.session_state["chat_messages"] = []
            st.rerun()

    # Export buttons (only when a conversation with messages exists)
    has_content = (
        st.session_state["chat_conv_id"] is not None
        and _display_messages(st.session_state["chat_messages"])
    )
    if has_content:
        st.markdown("")
        st.markdown(
            '<div class="conv-list-header">Export</div>',
            unsafe_allow_html=True,
        )
        msgs = st.session_state["chat_messages"]

        st.download_button(
            "⬇ Markdown",
            _export_markdown(msgs).encode("utf-8"),
            file_name="conversation.md",
            mime="text/markdown",
            use_container_width=True,
            key="export_md",
        )
        st.download_button(
            "⬇ Plain text",
            _export_plaintext(msgs).encode("utf-8"),
            file_name="conversation.txt",
            mime="text/plain",
            use_container_width=True,
            key="export_txt",
        )
        st.download_button(
            "⬇ HTML",
            _export_html(msgs).encode("utf-8"),
            file_name="conversation.html",
            mime="text/html",
            use_container_width=True,
            key="export_html",
        )

    st.markdown(
        '<div class="retention-note">'
        "💡 Conversations auto-delete after 5 days of inactivity."
        "</div>",
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Main area — header
# ---------------------------------------------------------------------------

st.markdown("## 🤖 AI Agent")

# ---------------------------------------------------------------------------
# Chat history replay
# ---------------------------------------------------------------------------

display_messages = _display_messages(st.session_state["chat_messages"])

if not display_messages and st.session_state["chat_conv_id"] is None and not _prompt:
    st.markdown(
        '<div class="empty-hero">'
        '<div class="hero-icon">🤖</div>'
        '<div class="hero-title">Ask me about your German vocabulary</div>'
        '<div class="hero-hints">'
        "<em>\"Which words do I keep getting wrong?\"</em> · "
        "<em>\"Find words related to food\"</em> · "
        "<em>\"How is my practice accuracy?\"</em>"
        "</div></div>",
        unsafe_allow_html=True,
    )

for _i, msg in enumerate(display_messages):
    with st.chat_message(msg["role"]):
        _render_message_content(msg["content"])
        _copy_button(msg["content"], key=f"copy_{msg['role']}_{_i}")

# ---------------------------------------------------------------------------
# Process pending message — renders between history and composer
# ---------------------------------------------------------------------------

if _prompt:
    with st.chat_message("user"):
        if _attached_for_send:
            st.image(
                f"data:{_attached_for_send['mime']};base64,"
                f"{_attached_for_send['b64']}",
                width=200,
            )
        st.markdown(_prompt)
        _copy_button(_prompt, key="copy_stream_user")

    con = open_db(db_path)
    try:
        conv_id = st.session_state["chat_conv_id"]

        # Create conversation on first message
        if conv_id is None:
            title = _generate_conversation_title(_prompt)
            conv_id = storage.create_conversation(con, title)
            st.session_state["chat_conv_id"] = conv_id

        # Save user message (text only — images are ephemeral)
        storage.save_message(con, conv_id, "user", _prompt)

        # Build OpenAI message list from full DB history
        db_msgs = storage.load_messages(con, conv_id)
        openai_messages = _build_openai_messages(db_msgs)

        # Inject attached image into the last user message for the API
        if _attached_for_send:
            _last = openai_messages[-1]
            _last["content"] = [
                {"type": "text", "text": _last["content"]},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": (
                            f"data:{_attached_for_send['mime']};base64,"
                            f"{_attached_for_send['b64']}"
                        ),
                    },
                },
            ]

        # Run agent with streaming
        chat_result = ChatResult()
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                response_text = st.write_stream(
                    run_chat(con, openai_messages, chat_result)
                )
            _copy_button(
                chat_result.assistant_content, key="copy_stream_resp"
            )

        # Persist intermediate messages (tool calls + responses)
        for imsg in chat_result.intermediate_messages:
            tc_json = None
            tc_id = None
            content = imsg.get("content")

            if imsg.get("tool_calls"):
                tc_json = json.dumps(imsg["tool_calls"], ensure_ascii=False)
            if imsg.get("tool_call_id"):
                tc_id = imsg["tool_call_id"]

            storage.save_message(
                con,
                conv_id,
                imsg["role"],
                content,
                tool_calls_json=tc_json,
                tool_call_id=tc_id,
            )

        # Persist final assistant response
        storage.save_message(
            con, conv_id, "assistant", chat_result.assistant_content
        )

        # Refresh in-memory messages from DB
        st.session_state["chat_messages"] = storage.load_messages(
            con, conv_id
        )

    finally:
        con.close()

# ---------------------------------------------------------------------------
# Custom composer bar:  [ + ]  [ text input .................. [↑] ]
# ---------------------------------------------------------------------------

# Determine composer state: active (has messages) or empty (fresh)
_is_active = (
    bool(display_messages)
    or st.session_state["chat_conv_id"] is not None
    or bool(_prompt)
)
_composer_cls = "cb-active" if _is_active else "cb-empty"

# Attachment chip (above composer when a file is queued)
if st.session_state.get("_attached_image"):
    _att = st.session_state["_attached_image"]
    _ac1, _ac2 = st.columns([0.92, 0.08])
    with _ac1:
        st.markdown(
            f'<div class="attach-chip">📎 {html_lib.escape(_att["name"])}'
            "</div>",
            unsafe_allow_html=True,
        )
    with _ac2:
        if st.button("✕", key="_clear_attach", help="Remove attachment"):
            st.session_state.pop("_attached_image", None)
            st.session_state["_upload_counter"] += 1
            st.rerun()

_c_attach, _c_input, _c_send = st.columns([1, 11, 1])

with _c_attach:
    # Hidden marker that CSS uses to identify and style the composer bar
    st.markdown(
        f'<div class="cb-marker {_composer_cls}"></div>',
        unsafe_allow_html=True,
    )
    with st.popover("\\+"):
        st.caption("Attach an image to your next message (max 5 MB).")
        _uploaded = st.file_uploader(
            "Image",
            type=_ACCEPTED_IMAGE_TYPES,
            label_visibility="collapsed",
            key=f"_img_uploader_{st.session_state['_upload_counter']}",
        )
        if _uploaded is not None:
            if _uploaded.size > _MAX_UPLOAD_MB * 1024 * 1024:
                st.error(f"Too large (max {_MAX_UPLOAD_MB} MB).")
            else:
                _raw = _uploaded.read()
                _b64 = base64.b64encode(_raw).decode()
                st.session_state["_attached_image"] = {
                    "b64": _b64,
                    "mime": _uploaded.type,
                    "name": _uploaded.name,
                }
                st.image(_raw, width=150)
                st.caption(f"✓ {_uploaded.name} ready")

with _c_input:
    st.text_input(
        "Message",
        placeholder="Ask about your German vocabulary...",
        label_visibility="collapsed",
        key=f"_chat_prompt_{st.session_state['_input_key_ctr']}",
        on_change=_mark_send,
    )

with _c_send:
    st.button(
        "↑",
        type="primary",
        on_click=_mark_send,
    )

# ---------------------------------------------------------------------------
# Layout-variable injection (active state only)
# Sets CSS custom properties on <html> so the fixed composer bar can
# align horizontally with the main content area and use the correct
# background colour for the gradient fade.
# ---------------------------------------------------------------------------

if _is_active:
    components.html(
        """
        <script>
        (function() {
            var d = parent.document;

            function applyLayout() {
                try {
                    var block = d.querySelector('[data-testid="stMainBlockContainer"]');
                    if (block) {
                        var r = block.getBoundingClientRect();
                        d.documentElement.style.setProperty('--cb-left',  r.left + 'px');
                        d.documentElement.style.setProperty('--cb-right',
                            (parent.innerWidth - r.right) + 'px');
                    }
                } catch(e) {}
            }

            function applyTheme() {
                try {
                    var app = d.querySelector('[data-testid="stApp"]');
                    if (!app) return;
                    var bg = parent.getComputedStyle(app).backgroundColor;
                    var m = bg.match(/\d+/g);
                    if (m && m.length >= 3) {
                        var val = 'rgba(' + m[0] + ',' + m[1] + ',' + m[2] + ',0.92)';
                        /* Only update if value actually changed to
                           avoid unnecessary style recalcs.          */
                        var cur = d.documentElement.style.getPropertyValue('--cb-footer-bg');
                        if (cur !== val) {
                            d.documentElement.style.setProperty('--cb-footer-bg', val);
                        }
                    }
                } catch(e) {}
            }

            /* Run immediately + delayed for initial render. */
            applyLayout();
            applyTheme();
            setTimeout(function() { applyLayout(); applyTheme(); }, 150);

            /* Persistent observer: watch stApp for class/style changes
               which Streamlit triggers on theme switches.  This keeps
               --cb-footer-bg in sync even without a Python re-run.
               Guard with a flag so multiple reruns don't stack observers. */
            if (!parent.__cbThemeObserver) {
                var app = d.querySelector('[data-testid="stApp"]');
                if (app) {
                    parent.__cbThemeObserver = new MutationObserver(function() {
                        applyTheme();
                    });
                    parent.__cbThemeObserver.observe(app, {
                        attributes: true,
                        attributeFilter: ['class', 'style']
                    });
                }
                /* Also track sidebar resize for layout vars. */
                parent.addEventListener('resize', applyLayout);
            }
        })();
        </script>
        """,
        height=0,
    )
