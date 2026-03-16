"""
src.vocab_export_core
~~~~~~~~~~~~~~~~~~~~~
Core functions for GPT-4o vocabulary enrichment.

Extracted from src/anki_vocab_export.py so they can be imported by the
Streamlit app without triggering module-level side effects (file I/O,
print statements, timestamp generation).
"""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Return a lazily-initialised OpenAI client."""
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


def clean_text(raw_text: str) -> list[str]:
    """Split a multi-line string into a clean list of phrases."""
    return [line.strip() for line in raw_text.splitlines() if line.strip()]


def get_vocabulary_data(phrases_list: list[str]) -> list[dict] | None:
    """Call GPT-4o to enrich a list of German phrases.

    Returns a list of dicts, each with keys:
        ``deutsch``, ``deutsch_mit_artikel``, ``englisch``, ``afrikaans``,
        ``hinweise``

    Returns ``None`` on any error.
    """
    system_prompt = """
    You are an expert German language tutor and data processor. The user will provide a list of German phrases or words.
    Your task is to process each item and return a single JSON object. The JSON object should contain one key, "vocabulary", which is a list of objects.
    Each object in the list must contain the following five keys: "deutsch", "deutsch_mit_artikel", "englisch", "afrikaans", and "hinweise".

    - `deutsch`: The original German phrase.
    - `deutsch_mit_artikel`: If the phrase contains a noun that needs an article, add it (e.g., "Kürbis" -> "der Kürbis"). For full sentences or non-nouns, this can be the same as the "deutsch" field.
    - `englisch`: The English translation.
    - `afrikaans`: The Afrikaans translation.
    - `hinweise`: The part of speech (Wortart), gender (Genus) for nouns, and any other helpful notes.

    Do not include any other text, explanations, or markdown formatting outside of the final JSON object.
    """

    user_content = "\n".join(phrases_list)

    try:
        response = _get_client().chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
        )
        response_data = json.loads(response.choices[0].message.content)
        return response_data["vocabulary"]
    except Exception as e:
        raise RuntimeError(f"OpenAI API error: {e}") from e
