"""
german_pipeline.grade
~~~~~~~~~~~~~~~~~~~~~
Answer grading for vocabulary drills.

Grading strategy
----------------
**Article drills** are always graded with strict normalised equality — the
user either knows the article or they don't.

**Short ``en_to_de`` answers** (normalised gold length
< ``_STRICT_LENGTH_THRESHOLD`` characters) also use strict equality, because
minor character differences in a short word are genuine mistakes, not
transcription noise.

**Long ``en_to_de`` answers** (normalised gold ≥ threshold) use fuzzy
similarity via ``difflib.SequenceMatcher`` so that small typos or punctuation
differences in full sentences don't cause an instant fail:

* ``ratio ≥ _CORRECT_RATIO``                  → **correct**
* ``_NEAR_MISS_RATIO ≤ ratio < _CORRECT_RATIO`` → **near miss** (incorrect,
  but flagged distinctly so the CLI can give encouraging feedback)
* ``ratio < _NEAR_MISS_RATIO``                 → **incorrect**

Error tags
----------
``""``           Correct answer (any mode), or incorrect long answer below
                 the near-miss threshold.
``"article"``    Wrong article on an ``"article"`` drill.
``"near_miss"``  Fuzzy answer in the near-miss band (0.80 ≤ ratio < 0.92).
"""

from __future__ import annotations

import difflib
import re

# ---------------------------------------------------------------------------
# Tuneable constants
# ---------------------------------------------------------------------------

#: Normalised gold-answer length below which strict equality is enforced.
_STRICT_LENGTH_THRESHOLD: int = 25

#: Fuzzy-match ratio at or above which an answer is counted as correct.
_CORRECT_RATIO: float = 0.92

#: Fuzzy-match ratio at or above which an answer is counted as a near miss.
_NEAR_MISS_RATIO: float = 0.80

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_WHITESPACE_RE: re.Pattern[str] = re.compile(r"\s+")


def _normalize(s: str) -> str:
    """Strip, collapse internal whitespace, and casefold *s*."""
    return _WHITESPACE_RE.sub(" ", s.strip()).casefold()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def grade(
    drill_type: str,
    gold_answer: str,
    user_answer: str,
) -> tuple[bool, str, float | None]:
    """Grade *user_answer* against *gold_answer* for the given *drill_type*.

    Parameters
    ----------
    drill_type:
        One of ``"en_to_de"``, ``"article"``.
    gold_answer:
        The expected correct answer (as returned by ``drills.pick_drill``).
    user_answer:
        The raw string typed by the user.

    Returns
    -------
    ``(is_correct, error_tags, similarity)``
        ``is_correct`` — ``True`` when the answer is correct.

        ``error_tags`` — one of:

        * ``""``          correct answer, or incorrect below near-miss
        * ``"article"``   wrong article drill answer
        * ``"near_miss"`` fuzzy answer in the 0.80 – 0.92 band

        ``similarity`` — ``float`` in [0, 1] when a
        ``SequenceMatcher`` ratio was computed (fuzzy mode, non-exact
        result); ``None`` for strict-mode comparisons or exact matches
        (no ratio needed).
    """
    norm_gold = _normalize(gold_answer)
    norm_user = _normalize(user_answer)

    # ── Exact match short-circuits everything ─────────────────────────────
    if norm_gold == norm_user:
        return True, "", None

    # ── Article drills are always strict (no fuzzy matching) ──────────────
    if drill_type == "article":
        return False, "article", None

    # ── Short answers: strict equality only ───────────────────────────────
    if len(norm_gold) < _STRICT_LENGTH_THRESHOLD:
        return False, "", None

    # ── Long answers: fuzzy similarity ────────────────────────────────────
    ratio: float = difflib.SequenceMatcher(None, norm_user, norm_gold).ratio()

    if ratio >= _CORRECT_RATIO:
        return True, "", ratio

    if ratio >= _NEAR_MISS_RATIO:
        return False, "near_miss", ratio

    return False, "", ratio
