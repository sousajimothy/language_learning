"""
german_pipeline.agent
~~~~~~~~~~~~~~~~~~~~~
GPT-4o agent with function calling for vocabulary exploration.

Provides a bounded set of tool functions that query the practice database
and a streaming chat loop that handles multi-round tool calls.  The model
never sees raw SQL — all data access goes through the tool functions below.

Design notes
------------
* Tool outputs use stable, structured shapes with ``vocab_id`` preserved
  in every payload — this keeps a clean upgrade path for future
  embeddings, graph retrieval, or practice-round handoff.
* Theme-related queries use a dedicated ``get_theme_candidates`` tool
  that performs bounded local retrieval (LIKE search across de/en/notes)
  rather than paging through the entire corpus.
* ``get_all_vocab_summary`` exists as a constrained browsing fallback
  with a hard-capped page size.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Generator

from dotenv import load_dotenv
from openai import OpenAI

from german_pipeline import storage

load_dotenv()

# ---------------------------------------------------------------------------
# OpenAI client (lazy singleton — same pattern as src/vocab_export_core.py)
# ---------------------------------------------------------------------------

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Return a lazily-initialised OpenAI client."""
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY not found in environment. "
                "Add it to .env at the repo root."
            )
        _client = OpenAI(api_key=api_key)
    return _client


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a helpful German language learning assistant. The user is studying \
German vocabulary and practising with flashcards and drills.

You have access to the user's vocabulary database through tool functions. \
Use them to answer questions about their vocabulary, identify weak areas, \
suggest study strategies, and provide linguistic explanations.

Guidelines:
- Always use the tool functions to look up data — never guess vocabulary \
  contents or statistics.
- For theme-related queries (e.g. "words related to the kitchen"), use the \
  get_theme_candidates tool first. It performs a bounded search across \
  multiple fields and returns a manageable candidate set.
- Only use get_all_vocab_summary as a last resort for open-ended browsing \
  when no other tool fits. Prefer targeted searches.
- Present results in clear markdown: use tables for vocabulary lists, \
  bold for emphasis, and bullet points for summaries.
- When discussing accuracy or performance, include specific numbers.
- Keep responses concise but thorough.
- You can answer general German language questions without using tools.
"""

# ---------------------------------------------------------------------------
# Tool schemas (OpenAI function calling format)
# ---------------------------------------------------------------------------

TOOLS_SCHEMA: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_vocab",
            "description": (
                "Search vocabulary items by keyword across German text, "
                "English translation, article forms, and notes fields. "
                "Use for exact or partial keyword lookups."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search keyword or phrase",
                    },
                    "field": {
                        "type": ["string", "null"],
                        "description": (
                            "Restrict search to one field, or null to "
                            "search all fields. Allowed: de, en, "
                            "de_mit_artikel, notes."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (1–50, default 25)",
                    },
                },
                "required": ["query", "field", "limit"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_theme_candidates",
            "description": (
                "Find vocabulary items related to a theme or topic. "
                "Searches across German, English, and notes fields using "
                "multiple keyword variants. Use this as the primary tool "
                "for theme-related queries like 'kitchen words', 'travel "
                "vocabulary', 'food items', etc."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "theme": {
                        "type": "string",
                        "description": (
                            "Theme or topic to search for (e.g. 'kitchen', "
                            "'food', 'travel')"
                        ),
                    },
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Additional keywords and synonyms to broaden "
                            "the search (e.g. for 'kitchen': ['Küche', "
                            "'cook', 'kochen', 'food', 'Essen', 'recipe']). "
                            "Include both German and English variants."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (1–100, default 50)",
                    },
                },
                "required": ["theme", "keywords", "limit"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_worst_items",
            "description": (
                "Get the worst-performing vocabulary items based on "
                "practice accuracy within a rolling time window."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {
                        "type": "integer",
                        "description": "Number of items to return (1–50)",
                    },
                    "days": {
                        "type": "integer",
                        "description": "Look-back window in days (1–365)",
                    },
                },
                "required": ["n", "days"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_item_detail",
            "description": (
                "Get full details and practice statistics for specific "
                "vocabulary items by their IDs."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "vocab_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Vocabulary item IDs (max 20)",
                    },
                },
                "required": ["vocab_ids"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_practice_summary",
            "description": (
                "Get overall practice statistics: total vocabulary count, "
                "attempts, accuracy rate, and near-miss rate."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Look-back window in days (1–365)",
                    },
                },
                "required": ["days"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_sources",
            "description": "List all vocabulary sources with item counts.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_all_vocab_summary",
            "description": (
                "Paginated summary of all vocabulary items (id, German, "
                "English, notes). This is a FALLBACK browsing tool — "
                "prefer search_vocab or get_theme_candidates for targeted "
                "queries. Page size is hard-capped at 100."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Page size (1–100)",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Number of items to skip",
                    },
                },
                "required": ["limit", "offset"],
                "additionalProperties": False,
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

_ALLOWED_SEARCH_FIELDS = {"de", "en", "de_mit_artikel", "notes"}


def _tool_search_vocab(
    con: sqlite3.Connection,
    query: str,
    field: str | None = None,
    limit: int = 25,
) -> list[dict]:
    """LIKE search across ``vocab_items``."""
    limit = max(1, min(limit, 50))
    like_val = f"%{query}%"

    if field and field in _ALLOWED_SEARCH_FIELDS:
        where = f"{field} LIKE ?"
        params: tuple = (like_val,)
    else:
        where = (
            "de LIKE ? OR en LIKE ? OR de_mit_artikel LIKE ? OR notes LIKE ?"
        )
        params = (like_val, like_val, like_val, like_val)

    old_factory = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            f"SELECT id, de, de_mit_artikel, en, notes, source "
            f"FROM vocab_items WHERE {where} LIMIT ?",
            params + (limit,),
        ).fetchall()
    finally:
        con.row_factory = old_factory
    return [dict(r) for r in rows]


def _tool_get_theme_candidates(
    con: sqlite3.Connection,
    theme: str,
    keywords: list[str] | None = None,
    limit: int = 50,
) -> dict:
    """Bounded theme search across multiple fields and keywords.

    Searches ``de``, ``en``, ``de_mit_artikel``, and ``notes`` for the
    theme string and each keyword.  Results are de-duplicated by vocab id
    and capped at *limit*.

    Returns ``{theme, total_matches, items: [{id, de, de_mit_artikel,
    en, notes, source}]}``.  The stable shape with ``id`` preserved
    supports future upgrade to embedding-based retrieval.
    """
    limit = max(1, min(limit, 100))
    all_terms = [theme] + (keywords or [])
    # De-dup terms (case-insensitive)
    seen: set[str] = set()
    unique_terms: list[str] = []
    for t in all_terms:
        t_lower = t.strip().lower()
        if t_lower and t_lower not in seen:
            seen.add(t_lower)
            unique_terms.append(t.strip())

    if not unique_terms:
        return {"theme": theme, "total_matches": 0, "items": []}

    # Build OR conditions: for each term, check de/en/de_mit_artikel/notes
    conditions: list[str] = []
    params: list[str] = []
    for term in unique_terms:
        like = f"%{term}%"
        conditions.append(
            "(de LIKE ? OR en LIKE ? OR de_mit_artikel LIKE ? OR notes LIKE ?)"
        )
        params.extend([like, like, like, like])

    where = " OR ".join(conditions)

    old_factory = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            f"SELECT DISTINCT id, de, de_mit_artikel, en, notes, source "
            f"FROM vocab_items WHERE {where} LIMIT ?",
            tuple(params) + (limit,),
        ).fetchall()
    finally:
        con.row_factory = old_factory

    items = [dict(r) for r in rows]
    return {"theme": theme, "total_matches": len(items), "items": items}


def _tool_get_worst_items(
    con: sqlite3.Connection, n: int = 10, days: int = 30
) -> list[dict]:
    """Wrap ``storage.query_worst_items`` with all-source default."""
    n = max(1, min(n, 50))
    days = max(1, min(days, 365))
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).replace(microsecond=0).isoformat()
    return storage.query_worst_items(
        con, cutoff, n, default_pipeline_only=False,
    )


def _tool_get_item_detail(
    con: sqlite3.Connection, vocab_ids: list[int]
) -> list[dict]:
    """Fetch full vocab rows + attempt stats for up to 20 IDs."""
    vocab_ids = [int(v) for v in vocab_ids[:20]]
    if not vocab_ids:
        return []

    rows = storage.fetch_vocab_by_ids(con, vocab_ids)

    # Enrich each row with attempt statistics
    for row in rows:
        vid = row["id"]
        stats = con.execute(
            "SELECT COUNT(*) AS total_attempts, "
            "COALESCE(AVG(is_correct), 0.0) AS accuracy, "
            "MAX(ts) AS last_seen "
            "FROM attempts WHERE vocab_id = ?",
            (vid,),
        ).fetchone()
        row["total_attempts"] = stats[0]
        row["accuracy"] = round(stats[1], 3)
        row["last_seen"] = stats[2]

    return rows


def _tool_get_practice_summary(
    con: sqlite3.Connection, days: int = 30
) -> dict:
    """Wrap ``storage.query_stats``."""
    days = max(1, min(days, 365))
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).replace(microsecond=0).isoformat()
    stats = storage.query_stats(con, cutoff, default_pipeline_only=False)
    # Return a clean subset (filter_label is internal)
    return {
        "vocab_count": stats["vocab_count"],
        "attempts_count": stats["attempts_count"],
        "accuracy": round(stats["accuracy"], 3),
        "near_miss_count": stats["near_miss_count"],
        "near_miss_rate": round(stats["near_miss_rate"], 3),
        "last_seen": stats["last_seen"],
    }


def _tool_list_sources(con: sqlite3.Connection) -> list[dict]:
    """Distinct sources with item counts."""
    rows = con.execute(
        "SELECT source, COUNT(*) AS count "
        "FROM vocab_items GROUP BY source ORDER BY source"
    ).fetchall()
    return [{"source": r[0], "count": r[1]} for r in rows]


def _tool_get_all_vocab_summary(
    con: sqlite3.Connection, limit: int = 100, offset: int = 0
) -> dict:
    """Paginated summary — hard-capped at 100 items per page."""
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    total = con.execute("SELECT COUNT(*) FROM vocab_items").fetchone()[0]

    old_factory = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT id, de, en, notes FROM vocab_items "
            "ORDER BY id LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    finally:
        con.row_factory = old_factory

    return {"total_count": total, "items": [dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

_TOOL_DISPATCH: dict[str, callable] = {
    "search_vocab": _tool_search_vocab,
    "get_theme_candidates": _tool_get_theme_candidates,
    "get_worst_items": _tool_get_worst_items,
    "get_item_detail": _tool_get_item_detail,
    "get_practice_summary": _tool_get_practice_summary,
    "list_sources": _tool_list_sources,
    "get_all_vocab_summary": _tool_get_all_vocab_summary,
}


def _dispatch_tool_call(
    con: sqlite3.Connection, name: str, arguments: dict
) -> dict | list:
    """Execute a tool function and return a JSON-serialisable result."""
    fn = _TOOL_DISPATCH.get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return fn(con, **arguments)
    except Exception as e:
        return {"error": f"Tool error ({name}): {e}"}


# ---------------------------------------------------------------------------
# Streaming chat loop
# ---------------------------------------------------------------------------

class ChatResult:
    """Container populated by :func:`run_chat` after streaming completes.

    Attributes
    ----------
    assistant_content : str
        The final assistant text response.
    intermediate_messages : list[dict]
        Tool-call round messages (assistant tool-call messages + tool
        response messages) that should be persisted for conversation
        continuity.
    """

    def __init__(self) -> None:
        self.assistant_content: str = ""
        self.intermediate_messages: list[dict] = []


#: Safety cap on tool-call round-trips per user message.
_MAX_TOOL_ROUNDS = 5


def run_chat(
    con: sqlite3.Connection,
    messages: list[dict],
    result: ChatResult,
) -> Generator[str, None, None]:
    """Stream an assistant response, executing tool calls as needed.

    Parameters
    ----------
    con:
        Open SQLite connection for tool execution.
    messages:
        OpenAI-format message history (without the system prompt — it is
        prepended automatically).
    result:
        Mutable container; ``assistant_content`` and
        ``intermediate_messages`` are populated when the generator is
        exhausted.

    Yields
    ------
    str
        Text chunks for streaming display.
    """
    client = _get_client()
    full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

    for _round in range(_MAX_TOOL_ROUNDS + 1):
        stream = client.chat.completions.create(
            model="gpt-4o",
            messages=full_messages,
            tools=TOOLS_SCHEMA,
            stream=True,
        )

        content_parts: list[str] = []
        tool_calls_acc: dict[int, dict] = {}

        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            if delta.content:
                content_parts.append(delta.content)
                yield delta.content

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {
                            "id": "",
                            "function": {"name": "", "arguments": ""},
                        }
                    if tc.id:
                        tool_calls_acc[idx]["id"] = tc.id
                    if tc.function and tc.function.name:
                        tool_calls_acc[idx]["function"]["name"] += (
                            tc.function.name
                        )
                    if tc.function and tc.function.arguments:
                        tool_calls_acc[idx]["function"]["arguments"] += (
                            tc.function.arguments
                        )

        # ── No tool calls → final text response ──────────────────────
        if not tool_calls_acc:
            result.assistant_content = "".join(content_parts)
            return

        # ── Tool calls → execute and loop ─────────────────────────────
        tool_calls_list = [
            tool_calls_acc[i] for i in sorted(tool_calls_acc)
        ]
        assistant_msg: dict = {
            "role": "assistant",
            "content": "".join(content_parts) or None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": tc["function"],
                }
                for tc in tool_calls_list
            ],
        }
        full_messages.append(assistant_msg)
        result.intermediate_messages.append(assistant_msg)

        for tc in tool_calls_list:
            fn_name = tc["function"]["name"]
            try:
                fn_args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                fn_args = {}
            tool_result = _dispatch_tool_call(con, fn_name, fn_args)

            # Keep payloads compact — truncate large lists in serialisation
            result_json = json.dumps(
                tool_result, ensure_ascii=False, default=str
            )
            # Hard cap tool result at ~32 KB to keep storage bounded
            if len(result_json) > 32_000:
                result_json = json.dumps(
                    {"error": "Result too large, truncated", "preview": result_json[:2000]},
                    ensure_ascii=False,
                )

            tool_msg: dict = {
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result_json,
            }
            full_messages.append(tool_msg)
            result.intermediate_messages.append(tool_msg)

    # Safety: exceeded max tool rounds
    result.assistant_content = (
        "".join(content_parts)
        if content_parts
        else "I wasn't able to complete the request within the allowed "
        "number of steps. Please try rephrasing your question."
    )
