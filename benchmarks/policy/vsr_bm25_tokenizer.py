#!/usr/bin/env python3
"""VSR bm25 2.3 English tokenization for XSR's bounded domain.

VSR uses bm25's default tokenizer: deunicode, lowercase, Unicode word
boundaries, NLTK English stop words, and the Snowball English (Porter2)
stemmer. Policy text is deliberately restricted to ASCII because the live eBPF
path cannot reproduce deunicode's unbounded one-to-many transliterations.
Query text accepts UTF-8 with every non-ASCII code point defined as a word
boundary. Within ASCII words, this module follows VSR's ordering and stemming.
"""

from __future__ import annotations

import re


# stop-words 0.9.0, src/nltk/english (the feature selected by bm25 2.3.2).
ENGLISH_STOP_WORDS = frozenset(
    """i me my myself we our ours ourselves you you're you've you'll you'd your yours
yourself yourselves he him his himself she she's her hers herself it it's its itself
they them their theirs themselves what which who whom this that that'll these those am
is are was were be been being have has had having do does did doing a an the and but if
or because as until while of at by for with about against between into through during
before after above below to from up down in out on off over under again further then once
here there when where why how all any both each few more most other some such no nor not
only own same so than too very s t can will just don don't should should've now d ll m o
re ve y ain aren aren't couldn couldn't didn didn't doesn doesn't hadn hadn't hasn hasn't
haven haven't isn isn't ma mightn mightn't mustn mustn't needn needn't shan shan't
shouldn shouldn't wasn wasn't weren weren't won won't wouldn wouldn't""".split()
)


# unicode-segmentation keeps ASCII contractions and decimal numbers as single
# words.  Underscore is an ExtendNumLet connector, but a bare underscore is not
# a word.  This is the ASCII subset relevant after deunicode normalization.
_ASCII_WORD = re.compile(
    r"[0-9]+(?:\.[0-9]+)+|[a-z0-9]+(?:_[a-z0-9]+)+|[a-z0-9]+(?:'[a-z0-9]+)*"
)
_VOWELS = frozenset("aeiouy")
_VALID_LI = frozenset("cdeghkmnrt")
_DOUBLES = ("bb", "dd", "ff", "gg", "mm", "nn", "pp", "rr", "tt")
_EXCEPTIONS = {
    "skis": "ski", "skies": "sky", "dying": "die", "lying": "lie",
    "tying": "tie", "idly": "idl", "gently": "gentl", "ugly": "ugli",
    "early": "earli", "only": "onli", "singly": "singl", "sky": "sky",
    "news": "news", "howe": "howe", "atlas": "atlas", "cosmos": "cosmos",
    "bias": "bias", "andes": "andes",
}
_POST_1A_EXCEPTIONS = frozenset(
    ("inning", "outing", "canning", "herring", "earring", "proceed", "exceed", "succeed")
)


def _regions(word: str) -> tuple[int, int]:
    if word.startswith(("gener", "arsen")):
        r1 = 5
    elif word.startswith("commun"):
        r1 = 6
    else:
        r1 = len(word)
        for index in range(1, len(word)):
            if word[index - 1] in _VOWELS and word[index] not in _VOWELS:
                r1 = index + 1
                break
    r2 = len(word)
    for index in range(r1 + 1, len(word)):
        if word[index - 1] in _VOWELS and word[index] not in _VOWELS:
            r2 = index + 1
            break
    return r1, r2


def _short_syllable(word: str) -> bool:
    if len(word) == 2:
        return word[0] in _VOWELS and word[1] not in _VOWELS
    return (
        len(word) >= 3
        and word[-3] not in _VOWELS
        and word[-2] in _VOWELS
        and word[-1] not in _VOWELS
        and word[-1] not in "wxyY"
    )


def _has_vowel(word: str) -> bool:
    return any(character in _VOWELS for character in word)


def stem_english(word: str) -> str:
    """Snowball English/Porter2, matching rust-stemmers 1.2.0 for ASCII."""
    if len(word) <= 2:
        return word
    if word.startswith("'"):
        word = word[1:]
    if word in _EXCEPTIONS:
        return _EXCEPTIONS[word]

    # Snowball marks consonantal y.  Uppercase Y is excluded from _VOWELS.
    marked = list(word)
    for index, character in enumerate(marked):
        if character == "y" and (index == 0 or marked[index - 1] in _VOWELS):
            marked[index] = "Y"
    word = "".join(marked)
    r1, r2 = _regions(word)

    # Step 0.
    for suffix in ("'s'", "'s", "'"):
        if word.endswith(suffix):
            word = word[: -len(suffix)]
            break

    # Step 1a.
    if word.endswith("sses"):
        word = word[:-2]
    elif word.endswith(("ied", "ies")):
        word = word[:-2] if len(word) > 4 else word[:-1]
    elif not word.endswith(("us", "ss")) and word.endswith("s"):
        if any(character in _VOWELS for character in word[:-2]):
            word = word[:-1]
    if word in _POST_1A_EXCEPTIONS:
        return word.replace("Y", "y")

    # Step 1b. Region positions are from the original marked word, as Snowball
    # specifies; suffix edits do not recompute them.
    if word.endswith("eedly"):
        if len(word) - 5 >= r1:
            word = word[:-3]
    elif word.endswith("eed"):
        if len(word) - 3 >= r1:
            word = word[:-1]
    else:
        for suffix in ("ingly", "edly", "ing", "ed"):
            if word.endswith(suffix) and _has_vowel(word[: -len(suffix)]):
                word = word[: -len(suffix)]
                if word.endswith(("at", "bl", "iz")):
                    word += "e"
                elif word.endswith(_DOUBLES):
                    word = word[:-1]
                elif r1 >= len(word) and _short_syllable(word):
                    word += "e"
                break

    # Step 1c.
    if len(word) > 2 and word.endswith(("y", "Y")) and word[-2] not in _VOWELS:
        word = word[:-1] + "i"

    # Step 2.
    step2 = (
        ("ization", "ize"), ("ational", "ate"), ("fulness", "ful"),
        ("ousness", "ous"), ("iveness", "ive"), ("tional", "tion"),
        ("biliti", "ble"), ("lessli", "less"), ("entli", "ent"),
        ("ation", "ate"), ("alism", "al"), ("aliti", "al"),
        ("ousli", "ous"), ("iviti", "ive"), ("fulli", "ful"),
        ("enci", "ence"), ("anci", "ance"), ("abli", "able"),
        ("izer", "ize"), ("ator", "ate"), ("alli", "al"), ("bli", "ble"),
    )
    replaced = False
    for suffix, replacement in step2:
        if word.endswith(suffix):
            if len(word) - len(suffix) >= r1:
                word = word[: -len(suffix)] + replacement
            replaced = True
            break
    if not replaced and word.endswith("ogi"):
        if len(word) - 3 >= r1 and word[-4:-3] == "l":
            word = word[:-1]
    elif not replaced and word.endswith("li"):
        if len(word) - 2 >= r1 and word[-3:-2] in _VALID_LI:
            word = word[:-2]

    # Step 3.
    for suffix, replacement, needs_r2 in (
        ("ational", "ate", False), ("tional", "tion", False),
        ("alize", "al", False), ("icate", "ic", False),
        ("iciti", "ic", False), ("ative", "", True),
        ("ical", "ic", False), ("ness", "", False), ("ful", "", False),
    ):
        if word.endswith(suffix):
            boundary = r2 if needs_r2 else r1
            if len(word) - len(suffix) >= boundary:
                word = word[: -len(suffix)] + replacement
            break

    # Step 4.
    removed = False
    for suffix in (
        "ement", "ance", "ence", "able", "ible", "ment", "ant", "ent",
        "ism", "ate", "iti", "ous", "ive", "ize", "al", "er", "ic",
    ):
        if word.endswith(suffix):
            if len(word) - len(suffix) >= r2:
                word = word[: -len(suffix)]
            removed = True
            break
    if not removed and word.endswith(("sion", "tion")) and len(word) - 3 >= r2:
        word = word[:-3]

    # Step 5.
    if word.endswith("e"):
        base = word[:-1]
        if len(base) >= r2 or (len(base) >= r1 and not _short_syllable(base)):
            word = base
    elif word.endswith("ll") and len(word) - 1 >= r2:
        word = word[:-1]
    return word.replace("Y", "y")


def tokenize(text: str) -> list[str]:
    """Strictly tokenize ASCII policy text."""
    return [stem_english(token) for token in ascii_words(text)]


def tokenize_query(text: str) -> list[str]:
    """Tokenize runtime text with non-ASCII code points as boundaries."""
    normalized = "".join(character if ord(character) < 128 else " " for character in text)
    return [
        stem_english(token)
        for token in _ASCII_WORD.findall(normalized.lower())
        if token not in ENGLISH_STOP_WORDS
    ]


def ascii_words(text: str) -> list[str]:
    """Return VSR-normalized, stop-word-filtered words before stemming."""
    try:
        normalized = text.encode("ascii").decode("ascii").lower()
    except UnicodeEncodeError as exc:
        raise ValueError(
            f"BM25 text {text!r} is outside XSR's exact ASCII tokenizer domain; "
            "VSR deunicode normalization cannot be reproduced generally in eBPF"
        ) from exc
    return [token for token in _ASCII_WORD.findall(normalized) if token not in ENGLISH_STOP_WORDS]


def is_ascii_word(text: str) -> bool:
    """Return whether one string is exactly one supported ASCII word token."""
    return text.isascii() and _ASCII_WORD.fullmatch(text.lower()) is not None
