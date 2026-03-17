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

import json
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

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

display_messages = [
    m for m in st.session_state["chat_messages"]
    if m["role"] in ("user", "assistant") and m.get("content")
]

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

for msg in display_messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ---------------------------------------------------------------------------
# Chat input
# ---------------------------------------------------------------------------

if prompt := st.chat_input("Ask about your German vocabulary..."):
    # Display user message immediately
    with st.chat_message("user"):
        st.markdown(prompt)

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

        # Save user message
        storage.save_message(con, conv_id, "user", prompt)

        # Build OpenAI message list from full DB history
        db_msgs = storage.load_messages(con, conv_id)
        openai_messages = _build_openai_messages(db_msgs)

        # Run agent with streaming
        chat_result = ChatResult()
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                response_text = st.write_stream(
                    run_chat(con, openai_messages, chat_result)
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
