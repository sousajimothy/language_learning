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

from german_pipeline import storage
from german_pipeline.agent import ChatResult, run_chat
from ui_utils import get_db_path, open_db


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

def _inject_css() -> None:
    st.markdown("""
<style>
/* ── AI Agent page styles ─────────────────────────────── */
.conv-list-header {
    font-size: 0.62rem;
    font-weight: 700;
    letter-spacing: 0.10em;
    text-transform: uppercase;
    color: color-mix(in srgb, var(--text-color) 35%, transparent);
    margin: 0.8rem 0 0.3rem;
}
.retention-note {
    font-size: 0.68rem;
    color: color-mix(in srgb, var(--text-color) 35%, transparent);
    margin-top: 0.6rem;
    padding: 0.4rem 0.5rem;
    border-radius: 6px;
    background: color-mix(in srgb, var(--text-color) 4%, transparent);
}

/* Attachment preview chip */
.attach-chip {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    background: color-mix(in srgb, var(--text-color) 6%, transparent);
    border: 1px solid color-mix(in srgb, var(--text-color) 15%, transparent);
    border-radius: 8px;
    padding: 0.35rem 0.75rem;
    font-size: 0.78rem;
    color: color-mix(in srgb, var(--text-color) 70%, transparent);
    margin: 0.2rem 0 0.5rem;
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
    """Render a compact copy-to-clipboard button via an HTML component."""
    safe_text = html_lib.escape(text)
    components.html(
        f"""
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ background: transparent; }}
            .cb {{
                all: unset;
                cursor: pointer;
                font-size: 11.5px;
                color: rgba(128,128,128,0.55);
                padding: 1px 9px;
                border: 1px solid rgba(128,128,128,0.18);
                border-radius: 5px;
                transition: all 0.15s;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            }}
            .cb:hover {{
                color: rgba(128,128,128,0.85);
                background: rgba(128,128,128,0.08);
                border-color: rgba(128,128,128,0.3);
            }}
        </style>
        <textarea id="ct"
                  style="position:fixed;opacity:0;pointer-events:none;left:-9999px"
        >{safe_text}</textarea>
        <button class="cb" onclick="
            var t=document.getElementById('ct');
            t.style.cssText='position:fixed;left:0;top:0;opacity:0.01';
            t.select(); t.setSelectionRange(0,999999);
            document.execCommand('copy');
            t.style.cssText='position:fixed;opacity:0;pointer-events:none;left:-9999px';
            this.textContent='\u2713 Copied';
            setTimeout(()=>this.textContent='\U0001f4cb Copy',1500);
        ">\U0001f4cb Copy</button>
        """,
        height=30,
        key=key,
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
                title = conv["title"][:35] or "Untitled"
                is_active = conv["id"] == st.session_state.get("chat_conv_id")
                btn_label = f"{'▸ ' if is_active else ''}{title}"
                if st.button(
                    btn_label,
                    key=f"conv_{conv['id']}",
                    use_container_width=True,
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
# Main area — header + attach
# ---------------------------------------------------------------------------

_hdr_left, _hdr_right = st.columns([10, 1])
with _hdr_left:
    st.markdown("## 🤖 AI Agent")
with _hdr_right:
    with st.popover("📎"):
        st.caption("Attach an image to your next message (max 5 MB).")
        _uploaded = st.file_uploader(
            "Image",
            type=_ACCEPTED_IMAGE_TYPES,
            label_visibility="collapsed",
            key=f"_img_uploader_{st.session_state['_upload_counter']}",
        )
        if _uploaded is not None:
            if _uploaded.size > _MAX_UPLOAD_MB * 1024 * 1024:
                st.error(f"File exceeds {_MAX_UPLOAD_MB} MB limit.")
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

# Attachment preview chip (visible when popover is closed)
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

# ---------------------------------------------------------------------------
# Chat history replay
# ---------------------------------------------------------------------------

display_messages = _display_messages(st.session_state["chat_messages"])

if not display_messages and st.session_state["chat_conv_id"] is None:
    st.markdown(
        '<div style="text-align:center;padding:3rem 1rem;'
        'color:color-mix(in srgb, var(--text-color) 40%, transparent);">'
        "<p style=\"font-size:2.5rem;margin-bottom:0.5rem;\">🤖</p>"
        "<p style=\"font-size:1rem;font-weight:600;\">Ask me about your German vocabulary</p>"
        "<p style=\"font-size:0.82rem;margin-top:0.3rem;\">"
        "Try: <em>\"Which words do I keep getting wrong?\"</em> · "
        "<em>\"Find words related to food\"</em> · "
        "<em>\"How is my practice accuracy?\"</em>"
        "</p></div>",
        unsafe_allow_html=True,
    )

for _i, msg in enumerate(display_messages):
    with st.chat_message(msg["role"]):
        _render_message_content(msg["content"])
        _copy_button(msg["content"], key=f"copy_{msg['role']}_{_i}")

# ---------------------------------------------------------------------------
# Chat input
# ---------------------------------------------------------------------------

if prompt := st.chat_input("Ask about your German vocabulary..."):
    # Grab any pending attachment before rendering
    _attached = st.session_state.pop("_attached_image", None)

    # Display user message immediately
    with st.chat_message("user"):
        if _attached:
            st.image(
                f"data:{_attached['mime']};base64,{_attached['b64']}",
                width=200,
            )
        st.markdown(prompt)
        _copy_button(prompt, key="copy_stream_user")

    con = open_db(db_path)
    try:
        conv_id = st.session_state["chat_conv_id"]

        # Create conversation on first message
        if conv_id is None:
            title = prompt[:50].strip()
            if len(prompt) > 50:
                title += "…"
            conv_id = storage.create_conversation(con, title)
            st.session_state["chat_conv_id"] = conv_id

        # Save user message (text only — images are ephemeral)
        storage.save_message(con, conv_id, "user", prompt)

        # Build OpenAI message list from full DB history
        db_msgs = storage.load_messages(con, conv_id)
        openai_messages = _build_openai_messages(db_msgs)

        # Inject attached image into the last user message for the API
        if _attached:
            _last = openai_messages[-1]
            _last["content"] = [
                {"type": "text", "text": _last["content"]},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": (
                            f"data:{_attached['mime']};base64,"
                            f"{_attached['b64']}"
                        ),
                    },
                },
            ]
            # Reset the file uploader widget
            st.session_state["_upload_counter"] += 1

        # Run agent with streaming
        chat_result = ChatResult()
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                response_text = st.write_stream(
                    run_chat(con, openai_messages, chat_result)
                )
            # Copy button for the just-streamed response
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
