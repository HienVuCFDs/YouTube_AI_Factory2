"""Mechanical check that a retelling did not introduce names or numbers.

The re-narration workflow exists for material that must stay correct: folk
tales people grew up with, historical accounts someone can look up, and other
people's work that is being retold rather than rewritten. Changing a character
name is not a style choice there.

An AI reviewer catches most of that, but it is the same kind of system that
produced the text, and an invented name reads perfectly well. So this does not
ask anyone: it pulls the proper nouns and the numbers out of both texts and
compares them. A name in the retelling that never appears in the source cannot
have come from the source, whatever any model says about it.

Deliberately one-directional. A retelling is shorter than its source and drops
things; that is compression, not invention. What it *asserts* that the source
never said is the fault this guards against.
"""

from __future__ import annotations

import re
import unicodedata

# Vietnamese sentences all start with a capital, so a capitalised word in first
# position says nothing. Words after that position are the usable signal.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+")
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_DIGITS = re.compile(r"\d[\d.,]*")

# Titles and honorifics are capitalised in Vietnamese writing without being
# the name itself: "Vua Hung" gives "Hung", which is the part worth checking.
_TITLE_WORDS = frozenset({
    "vua", "hoang", "chua", "ong", "ba", "anh", "chi", "em", "co", "chu", "bac",
    "cau", "di", "thay", "cha", "me", "con", "nguoi", "nang", "chang", "tuong",
    "quan", "hoangde", "thanh", "than", "but", "tien", "duc", "cu", "lao", "ngai",
})

# Words that start a clause and get capitalised in ordinary prose.
_SENTENCE_WORDS = frozenset({
    "va", "nhung", "roi", "tu", "khi", "neu", "vi", "boi", "cho", "de", "sau",
    "truoc", "trong", "ngoai", "tren", "duoi", "mot", "hai", "ba", "moi", "nay",
    "do", "ay", "the", "con", "cung", "nhu", "voi", "ma", "thi", "la", "co",
    "khong", "da", "se", "dang", "tai", "ve", "den", "di", "lai", "ra", "vao",
    "ngay", "dem", "nam", "thang", "tuan", "gio", "phut", "giay", "hom",
})


def _fold(text: str) -> str:
    """Lowercase and strip Vietnamese tone marks, so 'Lợi' and 'loi' compare."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return stripped.replace("đ", "d").replace("Đ", "d")


def proper_nouns(text: str) -> list[str]:
    """Capitalised words that are not merely starting a sentence.

    Returned in the retelling's own spelling, because that is what a person
    needs to see to find and fix the line.
    """
    found: dict[str, str] = {}
    for sentence in _SENTENCE_SPLIT.split(text or ""):
        words = _WORD.findall(sentence)
        # Position 0 is capitalised by grammar, so it carries no information.
        for word in words[1:]:
            if not word[:1].isupper():
                continue
            folded = _fold(word)
            if len(folded) < 2 or folded in _TITLE_WORDS or folded in _SENTENCE_WORDS:
                continue
            found.setdefault(folded, word)
    return [found[key] for key in sorted(found)]


def numbers(text: str) -> list[str]:
    """Digit groups, normalised so 1.000 and 1,000 are one number."""
    seen: dict[str, str] = {}
    for raw in _DIGITS.findall(text or ""):
        cleaned = raw.rstrip(".,")
        digits = re.sub(r"[.,]", "", cleaned)
        if digits:
            seen.setdefault(digits, cleaned)
    return [seen[key] for key in sorted(seen, key=lambda item: (len(item), item))]


def unsourced_details(source_text: str, narration: str) -> dict[str, list[str]]:
    """Names and numbers the retelling states that its source never did.

    Matching is done on folded text so tone marks and case cannot hide a name
    that is genuinely present, and a name is accepted wherever it appears in
    the source - including at the start of a sentence, where it would not have
    been detectable as a proper noun.
    """
    folded_source = _fold(source_text or "")
    source_numbers = {re.sub(r"[.,]", "", item) for item in numbers(source_text or "")}
    return {
        "names": [
            word for word in proper_nouns(narration)
            if _fold(word) not in folded_source
        ],
        "numbers": [
            item for item in numbers(narration)
            if re.sub(r"[.,]", "", item) not in source_numbers
        ],
    }
