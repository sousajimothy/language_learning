"""
german_pipeline.drills
~~~~~~~~~~~~~~~~~~~~~~
Drill generation for interactive vocabulary practice.

Drill types
-----------
``"en_to_de"``
    Prompt: "Translate to German: {en}"
    Answer: ``de_mit_artikel`` (preferred) or ``de``
    Offered for every item.

``"article"``
    Prompt: "Article? ___ {noun}"
    Answer: ``der`` / ``die`` / ``das``
    Only offered when the item is identified as a noun, i.e. when
    ``de_mit_artikel`` starts with der/die/das *or* ``notes`` contains
    the word "Substantiv".

``"cloze"``
    Prompt: the ``de`` sentence with the target substring replaced by
    ``"____"`` (displayed as "Fill in the blank: …").
    Answer: the exact target substring (``de_mit_artikel`` when it
    appears verbatim in ``de``).

    Eligibility (both must hold):

    1. ``de`` contains at least one space **and** (has punctuation OR
       has ``len(de) >= _CLOZE_MIN_LEN``).
    2. ``de_mit_artikel`` is non-empty **and** is a verbatim substring
       of ``de`` — guarantees a clean, unambiguous blank.

    Target selection: ``de_mit_artikel`` (article + noun for nouns, or
    whatever key phrase was stored) when it appears verbatim in ``de``.
    If it is absent, no cloze is generated for that item.

``"mcq_en_to_de"``
    Prompt: "Which German matches: {en}?" with four labelled options (A–D).
    Answer: user selects A/B/C/D (or 1/2/3/4); graded in cli.py.
    Only offered when the session pool has at least ``_MCQ_POOL_MIN`` items
    (needed to supply three plausible distractors).

    Distractor selection prefers same word-type category, same first letter
    of the core lemma, and similar display-string length; falls back to
    random pool items when the pool is small or homogeneous.

``"mcq_article"``
    Prompt: "Choose the correct article: ___ {noun}" with options der/die/das.
    Answer: user selects A/B/C (or 1/2/3); graded in cli.py.
    Only offered for noun items when pool is large enough.

    Candidate mix (per item, subject to pool size ≥ ``_MCQ_POOL_MIN``):

    * **nouns** — ``en_to_de`` + ``article`` + ``cloze``
      + ``mcq_en_to_de`` + ``mcq_article`` (if eligible)
    * **sentence/phrase items** — ``en_to_de`` + ``cloze`` + ``mcq_en_to_de``
    * **short vocab items** — ``en_to_de`` + ``mcq_en_to_de``
    * **small pool (< _MCQ_POOL_MIN)** — MCQ types omitted; same mix as Step 8
"""

from __future__ import annotations

import random
import re

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# All German definite articles, lower-cased and followed by a space so we can
# strip them cleanly.  All three are exactly 4 characters (article + space).
_ARTICLE_PREFIXES: tuple[str, ...] = ("der ", "die ", "das ")

# Matches "Substantiv" anywhere in the notes field (case-insensitive).
_NOUN_NOTES_RE: re.Pattern[str] = re.compile(r"\bSubstantiv\b", re.IGNORECASE)

# Punctuation characters that indicate a sentence/phrase (cloze eligibility).
_SENTENCE_PUNCT_RE: re.Pattern[str] = re.compile(
    r'[.,!?;:\"\'\-()\u2013\u2014\u00bf\u00a1]'
)

#: Minimum length of ``de`` (characters) to be considered sentence-like even
#: without punctuation.
_CLOZE_MIN_LEN: int = 30

#: Minimum number of session items required before MCQ drills are offered.
#: The pool must supply the target plus at least 3 distinct distractors.
_MCQ_POOL_MIN: int = 8


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_article_and_noun(de_mit_artikel: str) -> tuple[str, str] | None:
    """If *de_mit_artikel* starts with a definite article, return ``(article, noun)``.

    ``article`` is the lower-cased article (``"der"``, ``"die"``, or ``"das"``).
    ``noun`` is the remainder of the string with its original casing preserved.
    Returns ``None`` when no article is found.
    """
    lower = de_mit_artikel.lower()
    for prefix in _ARTICLE_PREFIXES:
        if lower.startswith(prefix):
            article  = prefix.rstrip()               # "der" / "die" / "das"
            noun     = de_mit_artikel[len(prefix):]  # original casing kept
            return article, noun
    return None


def _is_noun(item: dict) -> bool:
    """Return ``True`` when the vocab item is identifiable as a German noun.

    Two signals are checked; *either* is sufficient:

    1. ``notes`` contains the word "Substantiv" — the most reliable signal,
       set by the pipeline importer for every noun.
    2. ``de_mit_artikel`` starts with ``der/die/das`` **and** the remainder
       (the noun part) does not contain a period — this guards against
       sentences that happen to begin with a definite article
       (e.g. ``"Das Sofa ist bequem. Das Zimmer…"``).
    """
    de_mit = (item.get("de_mit_artikel") or "").strip()
    notes  = (item.get("notes") or "").strip()

    # Primary signal: notes explicitly mentions Substantiv
    if _NOUN_NOTES_RE.search(notes):
        return True

    # Fallback: article prefix — only accepted when the remainder looks like
    # a noun/noun-phrase (no sentence-ending punctuation, reasonably short)
    result = _extract_article_and_noun(de_mit)
    if result is not None:
        _, noun = result
        if "." not in noun and "!" not in noun and "?" not in noun:
            return True

    return False


def _is_sentence_eligible(item: dict) -> bool:
    """Return ``True`` when *item*'s ``de`` field looks like a sentence or phrase.

    Heuristic: ``de`` must contain at least one space (i.e. two or more words).
    Single-word entries (``"Hund"``, ``"nebenbei"``) are excluded since there
    is no surrounding context left after blanking.
    """
    de = (item.get("de") or "").strip()
    return " " in de


def _make_cloze(item: dict) -> tuple[str, str] | None:
    """Try to generate a cloze (fill-in-the-blank) drill for *item*.

    Returns ``(prompt, gold_answer)`` where *prompt* is the ``de`` sentence
    with the target substring replaced by ``"____"``, or ``None`` when cloze
    cannot be generated safely for this item.

    Generation rules
    ----------------
    1. **Sentence gate** — ``de`` must pass :func:`_is_sentence_eligible`.
    2. **Target** — ``de_mit_artikel`` must be non-empty **and** appear
       verbatim (case-sensitive substring) in ``de``.  The first occurrence
       is blanked.  If this condition is not met, ``None`` is returned —
       fail-fast rather than producing a broken or misleading blank.
    3. The replacement is ``de_mit_artikel → "____"`` on ``de`` (first
       occurrence only), giving the prompt shown to the user.

    Notes
    -----
    * For nouns this targets the full article + noun phrase (e.g. ``"der
      Hund"``), directly testing article recall in sentence context.
    * For phrase/sentence items whose ``de_mit_artikel`` is a sub-phrase,
      the same mechanism applies regardless of noun status.
    * ``gold_answer`` is the exact original substring, so :func:`grade.grade`
      can compare it with strict or fuzzy equality as appropriate for its
      length.
    """
    de     = (item.get("de") or "").strip()
    de_mit = (item.get("de_mit_artikel") or "").strip()

    # ── Sentence eligibility gate ──────────────────────────────────────────
    if not _is_sentence_eligible(item):
        return None

    # ── Target: de_mit_artikel must appear in de (case-insensitive) ──────
    # Rule 1 (any item):  de_mit_artikel non-empty and substring of de.
    # Rule 2 (noun only): same check; the noun phrase is de_mit_artikel.
    # Rule 3:             anything else → no cloze.
    #
    # We try case-sensitive first (fast path, preserves de_mit as-is).
    # If that fails we fall back to case-insensitive search and extract the
    # *actual* substring from de with its original casing.  This handles the
    # very common case where de_mit_artikel stores a lower-cased article
    # (e.g. "das Buch") but the word appears sentence-initially in de
    # (e.g. "Das Buch liegt…").  The extracted target is used as gold_answer
    # so grade._normalize() casefoldes both sides and matching still works.
    if not de_mit:
        return None

    if de_mit in de:
        target = de_mit
    else:
        idx = de.lower().find(de_mit.lower())
        if idx == -1:
            return None
        target = de[idx : idx + len(de_mit)]   # original casing from de

    # ── Build prompt ───────────────────────────────────────────────────────
    prompt = de.replace(target, "____", 1)

    # Guard: the prompt must contain some context beyond the blank itself.
    # If blanking de_mit_artikel consumed the entire de field, the user has
    # nothing to infer from.  Fall back to blanking just the last word of de
    # so that the leading words serve as context.
    context = prompt.replace("____", "").strip()
    if not context:
        words = de.split()
        if len(words) < 2:
            return None
        last_word = words[-1]
        prompt = " ".join(words[:-1]) + " ____"
        target = last_word

    # ── Append English hint ────────────────────────────────────────────────
    en = (item.get("en") or "").strip()
    if en:
        prompt = f"{prompt}\n  ({en})"

    return prompt, target


# ---------------------------------------------------------------------------
# MCQ helpers
# ---------------------------------------------------------------------------

def _german_display(item: dict) -> str:
    """Return the preferred German display string for *item*.

    Prefers ``de_mit_artikel`` (which includes the article for nouns),
    falling back to ``de``.
    """
    de_mit = (item.get("de_mit_artikel") or "").strip()
    return de_mit if de_mit else (item.get("de") or "").strip()


def _notes_type_token(item: dict) -> str:
    """Extract the leading word-type token from ``notes`` (lower-cased).

    Returns the first comma-separated, space-split token, e.g.
    ``"substantiv"``, ``"verb"``, ``"adjektiv"``.  Empty string when
    ``notes`` is absent or blank.
    """
    notes = (item.get("notes") or "").strip()
    if not notes:
        return ""
    return notes.split(",")[0].split()[0].lower()


def _core_lemma(item: dict) -> str:
    """Return the core lemma for first-letter comparison.

    For nouns: the noun word without its article (from ``de_mit_artikel``).
    For other items: ``de`` as-is.
    """
    if _is_noun(item):
        de_mit = (item.get("de_mit_artikel") or "").strip()
        parsed = _extract_article_and_noun(de_mit)
        if parsed is not None:
            return parsed[1]   # noun without article
    return (item.get("de") or "").strip()


def _select_mcq_distractors(
    target_item: dict,
    pool_items: list[dict],
    rng: random.Random,
    n: int = 3,
) -> list[dict]:
    """Select up to *n* distractor items for MCQ from *pool_items*.

    Candidates are ranked by a cheap similarity heuristic so distractors
    are plausible (same category) rather than obviously wrong:

    * **+2** — same leading word-type token in ``notes``
      (e.g. both ``"substantiv"``).
    * **+1** — same noun / non-noun classification (fallback when type
      tokens differ or are absent).
    * **+1** — same first letter of the core lemma (article stripped for
      nouns).
    * **+1** — similar display-string length
      (``|len(target) − len(candidate)| ≤ 5``).

    Within equal-score groups the order is randomised via *rng* (shuffle
    before stable sort).  The target item itself is always excluded.
    """
    target_id    = target_item.get("id")
    target_disp  = _german_display(target_item)
    target_type  = _notes_type_token(target_item)
    target_noun  = _is_noun(target_item)
    target_first = (_core_lemma(target_item)[:1] or "").lower()
    target_len   = len(target_disp)

    candidates = [
        it for it in pool_items
        if it.get("id") != target_id and _german_display(it) != target_disp
    ]

    def _score(it: dict) -> int:
        s   = 0
        tok = _notes_type_token(it)
        if tok and tok == target_type:
            s += 2
        elif _is_noun(it) == target_noun:
            s += 1
        first = (_core_lemma(it)[:1] or "").lower()
        if first and first == target_first:
            s += 1
        if abs(len(_german_display(it)) - target_len) <= 5:
            s += 1
        return s

    # Shuffle first so ties are broken randomly, then stable-sort by score.
    rng.shuffle(candidates)
    candidates.sort(key=_score, reverse=True)
    return candidates[:n]


def _make_mcq_en_to_de(
    target_item: dict,
    pool_items: list[dict],
    rng: random.Random,
) -> tuple[str, list[str], int] | None:
    """Generate an English → German multiple-choice drill.

    Returns ``(prompt, choices, correct_idx)`` where *choices* is a
    shuffled list of 4 German strings and *correct_idx* is the 0-based
    index of the correct answer.  Returns ``None`` when fewer than 3
    distractors are available in *pool_items*.
    """
    en          = (target_item.get("en") or "").strip()
    target_disp = _german_display(target_item)

    distractors = _select_mcq_distractors(target_item, pool_items, rng, n=3)
    if len(distractors) < 3:
        return None

    choices_tagged = [(target_disp, True)] + [
        (_german_display(d), False) for d in distractors
    ]
    rng.shuffle(choices_tagged)
    choices     = [c for c, _ in choices_tagged]
    correct_idx = next(i for i, (_, ok) in enumerate(choices_tagged) if ok)

    return f"Which German matches: {en}?", choices, correct_idx


def _make_mcq_article(
    target_item: dict,
    rng: random.Random,
) -> tuple[str, list[str], int] | None:
    """Generate an article multiple-choice drill: choose der / die / das.

    Returns ``(prompt, choices, correct_idx)`` or ``None`` when the item
    is not a noun or has no extractable article.
    """
    de_mit = (target_item.get("de_mit_artikel") or "").strip()
    parsed = _extract_article_and_noun(de_mit)
    if parsed is None:
        return None
    article, noun = parsed

    choices_tagged = [(a, a == article) for a in ("der", "die", "das")]
    rng.shuffle(choices_tagged)
    choices     = [c for c, _ in choices_tagged]
    correct_idx = next(i for i, (_, ok) in enumerate(choices_tagged) if ok)

    return f"Choose the correct article: ___ {noun}", choices, correct_idx


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def pick_drill(item: dict) -> tuple[str, str, str]:
    """Choose a drill for *item* and return ``(drill_type, prompt, gold_answer)``.

    Simple single-item version that uses the module-level :mod:`random`
    instance.  Does **not** support MCQ drill types (no pool available).
    For sessions that should include MCQ drills, use
    :func:`pick_drill_with_pool` instead.

    The drill type is selected uniformly at random from the set of drills
    that are applicable to the item:

    * ``"en_to_de"`` — always eligible.
    * ``"article"`` — only when the item is a noun *and* its article can be
      unambiguously extracted from ``de_mit_artikel``.
    * ``"cloze"`` — only when :func:`_make_cloze` produces a valid blank.

    Parameters
    ----------
    item:
        A dict with at minimum the keys ``de``, ``de_mit_artikel``, ``en``,
        and ``notes`` (as returned by the DB query in the practice command).

    Returns
    -------
    ``(drill_type, prompt, gold_answer)``
        All three are plain strings.  ``gold_answer`` is what the grader
        will compare the user's input against.
    """
    de_mit = (item.get("de_mit_artikel") or item.get("de") or "").strip()
    en     = (item.get("en") or "").strip()

    # Pre-compute cloze once (may be None if item is ineligible)
    cloze_data: tuple[str, str] | None = _make_cloze(item)

    # Build the pool of eligible drill types
    eligible: list[str] = ["en_to_de"]
    if _is_noun(item) and _extract_article_and_noun(de_mit) is not None:
        eligible.append("article")
    if cloze_data is not None:
        eligible.append("cloze")

    drill_type = random.choice(eligible)

    if drill_type == "en_to_de":
        return "en_to_de", f"Translate to German: {en}", de_mit

    if drill_type == "article":
        # ── article drill ──────────────────────────────────────────────────
        article, noun = _extract_article_and_noun(de_mit)  # type: ignore[misc]
        return "article", f"Article? ___ {noun}", article

    # ── cloze drill ────────────────────────────────────────────────────────
    cloze_prompt, gold_answer = cloze_data  # type: ignore[misc]
    return "cloze", cloze_prompt, gold_answer


def pick_drill_with_pool(
    item: dict,
    pool_items: list[dict],
    rng: random.Random,
    allowed_types: set[str] | None = None,
) -> tuple[str, str, str, list[str] | None, int | None] | None:
    """Choose a drill using session context and return a 5-tuple (or ``None``).

    Extended version of :func:`pick_drill` that accepts the full session
    item pool and an explicit :class:`random.Random` instance, enabling
    MCQ drill types that require distractors from the pool.

    Drill type eligibility (all apply from :func:`pick_drill`, plus):

    * ``"mcq_en_to_de"`` — when ``len(pool_items) >= _MCQ_POOL_MIN`` and
      :func:`_make_mcq_en_to_de` can build 3 distinct distractors.
    * ``"mcq_article"`` — when pool is large enough, item is a noun, and
      :func:`_make_mcq_article` returns a valid result.

    All eligible drill types receive equal weight in the random draw.

    Parameters
    ----------
    item:
        The vocab item to drill.
    pool_items:
        All items in the current practice session (including *item* itself).
    rng:
        :class:`random.Random` instance.  Pass ``random.Random(seed)`` for
        a reproducible session; ``random.Random()`` for non-deterministic.
    allowed_types:
        When ``None`` (default) all applicable drill types are considered —
        identical to the pre-Step-10 behaviour.  Pass a ``set`` of drill
        type strings to restrict the draw to that subset (e.g.
        ``{"article", "mcq_article"}`` for articles-only mode).

    Returns
    -------
    ``(drill_type, prompt, gold_answer, choices, correct_idx)``

    * **Non-MCQ drills** — ``choices`` and ``correct_idx`` are ``None``.
    * **MCQ drills** — ``choices`` is the list of option strings (A → last);
      ``correct_idx`` is 0-based; ``gold_answer`` equals
      ``choices[correct_idx]``.
    * **``None``** — returned when *no* eligible drill exists after applying
      *allowed_types*.  The caller should skip this item and try the next
      candidate.
    """
    de_mit = (item.get("de_mit_artikel") or item.get("de") or "").strip()
    en     = (item.get("en") or "").strip()

    # ── Pre-compute optional drills ───────────────────────────────────────
    # MCQ helpers consume rng state (distractor shuffle + choice shuffle)
    # before the drill-type draw so the rng sequence is deterministic given
    # the same seed, pool, and allowed_types.
    #
    # When allowed_types is None (mixed mode) we always pre-compute both MCQ
    # variants — identical to the original behaviour.  For non-mixed modes
    # we only compute what the mode actually needs, avoiding wasted rng
    # consumption for drill types that will never be used.
    cloze_data:   tuple | None = _make_cloze(item)
    mcq_en_data:  tuple | None = None
    mcq_art_data: tuple | None = None

    need_mcq_en  = allowed_types is None or "mcq_en_to_de" in allowed_types
    need_mcq_art = allowed_types is None or "mcq_article"  in allowed_types

    if len(pool_items) >= _MCQ_POOL_MIN:
        if need_mcq_en:
            mcq_en_data = _make_mcq_en_to_de(item, pool_items, rng)
        if need_mcq_art and _is_noun(item) and _extract_article_and_noun(de_mit) is not None:
            mcq_art_data = _make_mcq_article(item, rng)

    # ── Build eligible pool (filtered by allowed_types) ───────────────────
    eligible: list[str] = []
    if allowed_types is None or "en_to_de" in allowed_types:
        eligible.append("en_to_de")
    if _is_noun(item) and _extract_article_and_noun(de_mit) is not None:
        if allowed_types is None or "article" in allowed_types:
            eligible.append("article")
    if cloze_data is not None:
        if allowed_types is None or "cloze" in allowed_types:
            eligible.append("cloze")
    if mcq_en_data is not None:
        eligible.append("mcq_en_to_de")
    if mcq_art_data is not None:
        eligible.append("mcq_article")

    # No eligible drill type for this item under the current mode → sentinel.
    if not eligible:
        return None

    drill_type = rng.choice(eligible)

    if drill_type == "en_to_de":
        return "en_to_de", f"Translate to German: {en}", de_mit, None, None

    if drill_type == "article":
        article, noun = _extract_article_and_noun(de_mit)  # type: ignore[misc]
        return "article", f"Article? ___ {noun}", article, None, None

    if drill_type == "cloze":
        cloze_prompt, gold = cloze_data  # type: ignore[misc]
        return "cloze", cloze_prompt, gold, None, None

    if drill_type == "mcq_en_to_de":
        mcq_prompt, choices, correct_idx = mcq_en_data  # type: ignore[misc]
        return "mcq_en_to_de", mcq_prompt, choices[correct_idx], choices, correct_idx

    # ── mcq_article ───────────────────────────────────────────────────────
    mcq_prompt, choices, correct_idx = mcq_art_data  # type: ignore[misc]
    return "mcq_article", mcq_prompt, choices[correct_idx], choices, correct_idx
